import re
import json
import hashlib
import logging
from datetime import datetime
from typing import Any, Optional, cast, get_args
from urllib.parse import urlencode

from django.db.models import Q, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import BasePagination, Cursor, CursorPagination, PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.fields import JSONStringFilterField, JSONTolerantListField, OptionalBooleanField
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import NotificationViewed
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    ActivityScope,
    apply_activity_visibility_restrictions,
)
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.permissions import PremiumFeaturePermission
from posthog.tasks import exporter

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.source_authentication import get_export_source_authentication

from .field_discovery import AdvancedActivityLogFieldDiscovery
from .filters import AdvancedActivityLogFilterManager, validate_detail_filters
from .ocsf import ActivityLogOCSFSerializer
from .utils import get_activity_log_lookback_restriction

ACTIVITY_LOG_ORDERING_DESCENDING = "-created_at"
ACTIVITY_LOG_ORDERING_ASCENDING = "created_at"
ACTIVITY_LOG_ORDERING_CHOICES = [ACTIVITY_LOG_ORDERING_DESCENDING, ACTIVITY_LOG_ORDERING_ASCENDING]

ACTIVITY_LOG_SCHEMA_OCSF = "ocsf"


def activity_log_ordering(request: Request) -> tuple[str, str]:
    """Ordering tuple for the list endpoints, with `id` appended so ties break deterministically.

    Ascending exists so a polling client can persist a cursor and resume forward; descending can't
    advance because new rows always land at position 0. Values follow DRF's `OrderingFilter`
    grammar: a bare field name is ascending, a `-` prefix descending.
    """
    if request.query_params.get("ordering") == ACTIVITY_LOG_ORDERING_ASCENDING:
        return ("created_at", "id")
    return ("-created_at", "-id")


def restrict_loop_activity(queryset: QuerySet[ActivityLog], team_id: int, user) -> QuerySet[ActivityLog]:
    """Keep personal loops' config out of the team-wide activity feed.

    Loop activity is team-scoped in the log, but a personal loop is owner-only (see
    products/tasks/docs/LOOPS.md "Access control"). The static visibility manager can't express
    per-user ownership, so restrict `Loop`-scoped rows to the loops this user may actually see.
    Lazy import keeps the tasks product off this module's import path.
    """
    from products.tasks.backend.facade import loops as loops_facade  # noqa: PLC0415

    visible_ids = loops_facade.visible_loop_ids(team_id, user)
    return queryset.exclude(Q(scope="Loop") & ~Q(item_id__in=visible_ids))


def restrict_loop_activity_for_org(queryset: QuerySet[ActivityLog], organization_id, user) -> QuerySet[ActivityLog]:
    """Org-wide equivalent of `restrict_loop_activity`. The org route has no single `team_id`, so it
    can't build a per-team allowlist; instead deny other users' personal-loop rows across the org.

    Two filters, both required. The persisted per-row context (`detail.context.visibility` /
    `created_by_user_id`, snapshotted at log time) is the primary one: `ActivityLog` outlives its
    loop (project deletion cascades `Loop` rows away while the log keeps plain `team_id` /
    `organization_id`), so a live-row denylist alone would open another user's deleted personal-loop
    history to org admins. The live-row denylist stays on top so a currently-personal loop hides ALL
    its rows, including ones logged back when it was team-visible.

    No object-level loop RBAC here, deliberately: this route is restricted to org admins and owners
    (`OrganizationActivityLogPermission`), who pass the RBAC precheck for every object, so the
    filter the team route applies via `visible_loop_ids` would be a no-op on this one."""
    from products.tasks.backend.facade import loops as loops_facade  # noqa: PLC0415

    user_id = getattr(user, "id", None)
    persisted_personal = Q(scope="Loop") & Q(detail__context__visibility="personal")
    if user_id is not None:
        persisted_personal &= ~Q(detail__context__created_by_user_id=str(user_id))
    queryset = queryset.exclude(persisted_personal)

    hidden_ids = loops_facade.hidden_personal_loop_ids_for_org(organization_id, user)
    if not hidden_ids:
        return queryset
    return queryset.exclude(Q(scope="Loop") & Q(item_id__in=hidden_ids))


def restrict_canvas_activity(queryset: QuerySet[ActivityLog], team_id: int, user) -> QuerySet[ActivityLog]:
    """Keep personal-channel canvases' metadata out of the team-wide activity feed.

    Canvas activity is team-scoped in the log, but a canvas in a personal channel is
    owner-only (see `CanvasViewSet`). Restrict `Canvas`-scoped rows to canvases this
    user may actually see. Lazy import keeps the canvas product off this module's path.
    """
    from products.canvas.backend import activity_visibility as canvas_activity  # noqa: PLC0415

    visible_ids = canvas_activity.visible_canvas_ids(team_id, user)
    return queryset.exclude(Q(scope="Canvas") & ~Q(item_id__in=visible_ids))


def restrict_canvas_activity_for_org(queryset: QuerySet[ActivityLog], organization_id, user) -> QuerySet[ActivityLog]:
    """Org-wide equivalent of `restrict_canvas_activity`. The org route has no single
    `team_id`, so deny other users' personal-channel canvas rows across the org. Canvases
    are soft-deleted, so their visibility stays computable without a persisted snapshot.
    """
    from products.canvas.backend import activity_visibility as canvas_activity  # noqa: PLC0415

    hidden_ids = canvas_activity.hidden_personal_canvas_ids_for_org(organization_id, user)
    if not hidden_ids:
        return queryset
    return queryset.exclude(Q(scope="Canvas") & Q(item_id__in=hidden_ids))


def apply_organization_scoped_filter(
    queryset: QuerySet[ActivityLog], include_org_scoped: bool, team_id: int, organization_id
) -> QuerySet[ActivityLog]:
    """
    Filter activity log queryset by team/org.

    When include_org_scoped is True, includes both:
    - Records with team_id matching the given team
    - Records with team_id=NULL and organization_id matching (org-scoped records)

    When False, only filters by team_id.
    """
    if include_org_scoped:
        return queryset.filter(Q(team_id=team_id) | Q(team_id__isnull=True, organization_id=organization_id))
    else:
        return queryset.filter(team_id=team_id)


class ActivityLogSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = "__all__"

    def get_unread(self, obj: ActivityLog) -> bool:
        """is the date of this log item newer than the user's bookmark"""
        if "user" not in self.context:
            return False

        user_bookmark: Optional[NotificationViewed] = NotificationViewed.objects.filter(
            user=self.context["user"]
        ).first()

        if user_bookmark is None:
            return True
        else:
            bookmark_date = user_bookmark.last_viewed_activity_date
            return bookmark_date < obj.created_at.replace(microsecond=obj.created_at.microsecond // 1000 * 1000)


class TailFollowingCursorPagination(CursorPagination):
    """Cursor pagination that can keep a forward cursor alive after the stream is exhausted.

    Stock DRF returns `next: null` on the final page, which leaves a polling client nothing to
    resume from: a saved "last page" URL just replays that page, so the client has to fall back
    to a date filter plus deduplication. With `follow=true` the link stays valid, so a caller can
    store one cursor and re-poll it as new entries arrive - the pattern Okta's System Log API
    documents.

    Opt-in rather than implied by ascending order, because a live cursor changes the termination
    condition: a follower stops when `results` is empty, not when `next` is null. Leaving that on
    by default would make the obvious `while next: ...` loop run forever.

    Known gap: the cursor encodes `created_at` and filters strictly past it, so an entry written
    later but sharing the last-seen timestamp is not returned. That is inherent to a
    timestamp-positioned cursor and matches DRF's behavior mid-stream.
    """

    follow = False

    def get_next_link(self) -> Optional[str]:
        link = super().get_next_link()
        if link is not None or not self.follow:
            return link
        if self.ordering and str(self.ordering[0]).startswith("-"):
            # Descending walks into history and has a real end; there is no tail to follow.
            return None
        if not self.page:
            # Nothing new since the caller's position, so hand the same cursor back.
            return self.encode_cursor(self.cursor) if self.cursor else None
        position = self._get_position_from_instance(self.page[-1], self.ordering)
        # DRF's stub types Cursor.position as int, but at runtime it holds the string that
        # _get_position_from_instance returns.
        return self.encode_cursor(Cursor(offset=0, reverse=False, position=position))  # type: ignore[arg-type]


class ActivityLogPagination(BasePagination):
    def __init__(self):
        self.page_number_pagination = PageNumberPagination()
        self.cursor_pagination = TailFollowingCursorPagination()
        self.page_number_pagination.page_size = 100
        self.page_number_pagination.page_size_query_param = "page_size"
        self.page_number_pagination.max_page_size = 1000
        self.cursor_pagination.page_size = 100
        self.cursor_pagination.page_size_query_param = "page_size"
        self.cursor_pagination.max_page_size = 1000
        # `created_at` is not unique, and DRF encodes only the first ordering field in the cursor,
        # resolving ties with an offset. That offset is reproducible only when rows sharing a
        # timestamp come back in a stable order, which Postgres does not otherwise guarantee.
        self.cursor_pagination.ordering = ("-created_at", "-id")

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        if request.query_params.get("page"):
            return self.page_number_pagination.paginate_queryset(queryset, request, view)
        else:
            self.cursor_pagination.ordering = activity_log_ordering(request)
            self.cursor_pagination.follow = request.query_params.get("follow") == "true"
            return self.cursor_pagination.paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        if self.request and self.request.query_params.get("page"):
            return self.page_number_pagination.get_paginated_response(data)
        else:
            return self.cursor_pagination.get_paginated_response(data)

    def get_paginated_response_schema(self, schema):
        # The paginator picks cursor or page-number mode per request, so the schema has to describe
        # both. Cursor responses (the default) carry no `count`, so it is documented as an optional
        # property rather than a required one.
        cursor_schema = self.cursor_pagination.get_paginated_response_schema(schema)
        page_number_schema = self.page_number_pagination.get_paginated_response_schema(schema)
        cursor_schema["properties"]["count"] = page_number_schema["properties"]["count"]
        return cursor_schema


class ActivityLogScopeField(serializers.ChoiceField):
    def __init__(self, **kwargs):
        choices = get_args(ActivityScope)
        super().__init__(choices=choices, **kwargs)


class ActivityLogQueryParamsSerializer(serializers.Serializer):
    user = serializers.UUIDField(
        required=False,
        help_text="Filter by user UUID who performed the action.",
    )
    scope = ActivityLogScopeField(
        required=False,
        help_text='Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".',
    )
    scopes = serializers.ListField(
        child=ActivityLogScopeField(),
        required=False,
        help_text='Filter by multiple activity scopes, comma-separated. Values must be valid ActivityScope enum values. E.g. "FeatureFlag,Insight".',
    )
    item_id = serializers.CharField(
        required=False,
        help_text="Filter by the ID of the affected resource.",
    )
    ordering = serializers.ChoiceField(
        choices=ACTIVITY_LOG_ORDERING_CHOICES,
        required=False,
        default=ACTIVITY_LOG_ORDERING_DESCENDING,
        help_text=(
            "Sort by when the entry was created. Defaults to newest first. Use created_at for oldest "
            "first when polling for new entries, so a saved cursor picks up where the last request stopped."
        ),
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Page number for pagination. When provided, uses page-based pagination ordered by most recent first.",
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        default=100,
        help_text="Number of results per page (default: 100, max: 1000).",
    )


@extend_schema(tags=["activity_logs"], extensions={"x-product": "platform_features"})
class ActivityLogViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet, mixins.ListModelMixin):
    scope_object = "activity_log"
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    pagination_class = ActivityLogPagination
    filter_rewrite_rules = {"project_id": "team_id"}
    permission_classes = [PremiumFeaturePermission]
    premium_feature_on_cloud = AvailableFeature.AUDIT_LOGS

    @extend_schema(parameters=[ActivityLogQueryParamsSerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _should_skip_parents_filter(self) -> bool:
        """
        Skip parent filtering when team has receive_org_level_activity_logs enabled.
        We'll apply custom org-scoped filtering in safely_get_queryset instead.
        """
        return bool(self.team.receive_org_level_activity_logs)

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET.dict()

        queryset = apply_organization_scoped_filter(
            queryset, bool(self.team.receive_org_level_activity_logs), self.team_id, self.organization.id
        )

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))
        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))
        if params.get("scopes", None):
            scopes = str(params.get("scopes", "")).split(",")
            queryset = queryset.filter(scope__in=scopes)
        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if params.get("page"):
            queryset = queryset.order_by(*activity_log_ordering(self.request))

        lookback_date = get_activity_log_lookback_restriction(self.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        queryset = apply_activity_visibility_restrictions(queryset, self.request.user)
        queryset = restrict_loop_activity(queryset, self.team_id, self.request.user)
        queryset = restrict_canvas_activity(queryset, self.team_id, self.request.user)

        return queryset


_IP_FILTER_RE = re.compile(r"^[0-9a-fA-F:.*]+$")
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _validate_ip_or_wildcard(value: str) -> None:
    v = (value or "").strip()
    if not v or not _IP_FILTER_RE.match(v):
        raise serializers.ValidationError(
            "Invalid IP address format. Use a valid IPv4/IPv6 address or a wildcard like `203.0.113.*`."
        )
    if "*" in v:
        return  # wildcard patterns are accepted as-is
    if _IPV4_RE.match(v):
        if not all(int(octet) <= 255 for octet in v.split(".")):
            raise serializers.ValidationError(
                "Invalid IP address format. Use a valid IPv4/IPv6 address or a wildcard like `203.0.113.*`."
            )
        return
    if ":" not in v:
        raise serializers.ValidationError(
            "Invalid IP address format. Use a valid IPv4/IPv6 address or a wildcard like `203.0.113.*`."
        )


class AdvancedActivityLogFiltersSerializer(serializers.Serializer):
    start_date = serializers.DateTimeField(
        required=False,
        help_text="Lower bound on `created_at` (inclusive), ISO-8601.",
    )
    end_date = serializers.DateTimeField(
        required=False,
        help_text="Upper bound on `created_at` (inclusive), ISO-8601.",
    )
    users = JSONTolerantListField(
        child=serializers.UUIDField(),
        required=False,
        default=[],
        help_text="Filter by users who performed the activity (user UUIDs).",
    )
    scopes = JSONTolerantListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text='Filter by activity scopes (e.g. "FeatureFlag", "Insight").',
    )
    activities = JSONTolerantListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text='Filter by activity types (e.g. "created", "updated", "deleted").',
    )
    clients = JSONTolerantListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter by API clients that generated the activity (from x-posthog-client header).",
    )
    ip_addresses = JSONTolerantListField(
        child=serializers.CharField(validators=[_validate_ip_or_wildcard]),
        required=False,
        default=[],
        help_text=(
            "Filter by client IP addresses. Accepts exact IPv4/IPv6 values or wildcard patterns "
            "using `*` (e.g. `203.0.113.*`). Multiple entries are OR-combined."
        ),
    )
    team_ids = JSONTolerantListField(
        child=serializers.IntegerField(),
        required=False,
        default=[],
        help_text=(
            "Filter by project (team) IDs. Only honored on the organization-scoped endpoint; "
            "ignored on the project-scoped endpoint."
        ),
    )
    search_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-text search across the `detail` JSON column.",
    )
    detail_filters = JSONStringFilterField(
        required=False,
        help_text=(
            "JSON-encoded map of `detail` field paths to {operation, value} filters. "
            "Allowed operations: exact, contains, in."
        ),
    )
    hogql_filter = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Reserved for future HogQL-based filtering.",
    )
    was_impersonated = OptionalBooleanField(
        required=False,
        help_text="When set, filters rows where the actor was impersonating another user.",
    )
    is_system = OptionalBooleanField(
        required=False,
        help_text="When set, filters rows authored by the system (no user).",
    )
    item_ids = JSONTolerantListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter by the `item_id` of the affected resource(s).",
    )
    ordering = serializers.ChoiceField(
        choices=ACTIVITY_LOG_ORDERING_CHOICES,
        required=False,
        default=ACTIVITY_LOG_ORDERING_DESCENDING,
        help_text=(
            "Sort by when the entry was created. Defaults to newest first. Use created_at for oldest "
            "first when polling for new entries, so a saved cursor picks up where the last request stopped."
        ),
    )
    follow = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Keep the next link valid after the last entry, so the same cursor can be re-polled as "
            "new entries arrive. Only applies with oldest-first ordering. When following, stop on an "
            "empty results list rather than on a null next link."
        ),
    )
    schema = serializers.ChoiceField(
        choices=[ACTIVITY_LOG_SCHEMA_OCSF],
        required=False,
        help_text=(
            "Response format. Set to ocsf to return Open Cybersecurity Schema Framework events for "
            "ingestion into a security tool. Omit for the default PostHog format."
        ),
    )
    include_values = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Include the previous and new values of changed fields. Only applies when schema is ocsf. "
            "Values can contain the content of the changed object, which makes responses larger and "
            "sends that content to your security tool."
        ),
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Page number for pagination. When provided, uses page-based pagination ordered by most recent first.",
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        default=100,
        help_text="Number of results per page (default: 100, max: 1000).",
    )

    def validate_detail_filters(self, value: Any) -> dict[str, Any]:
        return validate_detail_filters(value)


class ActivityLogFlatExportSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField()
    project_id = serializers.CharField(source="team_id")
    user_first_name = serializers.CharField(source="user.first_name", default="")
    user_last_name = serializers.CharField(source="user.last_name", default="")
    user_email = serializers.CharField(source="user.email", default="")
    detail = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "organization_id",
            "project_id",
            "user_first_name",
            "user_last_name",
            "user_email",
            "activity",
            "scope",
            "item_id",
            "detail",
            "client",
            "ip_address",
            "created_at",
        ]

    def get_detail(self, obj):
        return json.dumps(obj.detail) if obj.detail else ""


class StaticFiltersSerializer(serializers.Serializer):
    users = serializers.ListField(child=serializers.DictField(), help_text="Users who have logged activity.")
    scopes = serializers.ListField(child=serializers.DictField(), help_text="Available activity scopes.")
    activities = serializers.ListField(child=serializers.DictField(), help_text="Available activity types.")
    clients = serializers.ListField(
        child=serializers.DictField(),
        help_text="API clients that have generated activity (from x-posthog-client header).",
    )


class AvailableFiltersResponseSerializer(serializers.Serializer):
    static_filters = StaticFiltersSerializer(help_text="Pre-computed filter options for scopes, activities, and users.")
    detail_fields = serializers.DictField(help_text="Discovered detail fields and their value distributions.")


@extend_schema(extensions={"x-product": "platform_features"})
class AdvancedActivityLogsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = ActivityLogSerializer
    pagination_class = ActivityLogPagination
    logger = logging.getLogger(__name__)
    filter_rewrite_rules = {"project_id": "team_id"}
    scope_object = "activity_log"
    scope_object_read_actions = ["list", "retrieve", "available_filters"]
    queryset = ActivityLog.objects.all()
    permission_classes = [PremiumFeaturePermission]
    premium_feature_on_cloud = AvailableFeature.AUDIT_LOGS

    def _should_skip_parents_filter(self) -> bool:
        """
        Skip parent filtering when team has receive_org_level_activity_logs enabled.
        We'll apply custom org-scoped filtering in safely_get_queryset instead.
        """
        return bool(self.team.receive_org_level_activity_logs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filter_manager = None
        self._field_discovery = None

    @property
    def filter_manager(self) -> AdvancedActivityLogFilterManager:
        if self._filter_manager is None:
            self._filter_manager = AdvancedActivityLogFilterManager()
        return self._filter_manager

    @property
    def field_discovery(self) -> AdvancedActivityLogFieldDiscovery:
        if self._field_discovery is None:
            self._field_discovery = AdvancedActivityLogFieldDiscovery(self.organization.id)
        return self._field_discovery

    def _make_filters_serializable(self, filters_data: dict) -> dict[str, Any]:
        serializable_filters: dict[str, Any] = {}
        for key, value in filters_data.items():
            if isinstance(value, datetime):
                serializable_filters[key] = value.isoformat()
            elif isinstance(value, list):
                serializable_filters[key] = [str(v) if hasattr(v, "hex") else v for v in value]
            else:
                serializable_filters[key] = value
        return serializable_filters

    def _generate_export_filename(self, filters_data: dict, export_format: str) -> str:
        filter_string = json.dumps(filters_data, sort_keys=True)
        # md5 is fine here since file name collisions have no security impact
        # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
        filter_hash = hashlib.md5(filter_string.encode()).hexdigest()[:6]

        has_filters = any(filters_data.values())

        current_date = datetime.now().strftime("%Y%m%d")
        filename_base = (
            f"activity_logs_{filter_hash}_{current_date}" if has_filters else f"activity_logs_all_{current_date}"
        )
        return filename_base

    def safely_get_queryset(self, queryset) -> QuerySet:
        queryset = queryset.select_related("user")

        queryset = apply_organization_scoped_filter(
            queryset,
            bool(self.team.receive_org_level_activity_logs),
            self.team_id,
            self.organization.id,
        )

        # Apply lookback restriction based on feature limits
        lookback_date = get_activity_log_lookback_restriction(self.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        queryset = apply_activity_visibility_restrictions(queryset, self.request.user)
        queryset = restrict_loop_activity(queryset, self.team_id, self.request.user)
        queryset = restrict_canvas_activity(queryset, self.team_id, self.request.user)

        return queryset.order_by(*activity_log_ordering(self.request))

    def _validated_query_params(self) -> dict[str, Any]:
        # Validate once so serializer selection and context read the same coerced values the
        # filters serializer produces, instead of re-parsing the raw query string.
        validated = getattr(self, "_validated_query_params_cache", None)
        if validated is None:
            serializer = AdvancedActivityLogFiltersSerializer(data=self.request.query_params)
            serializer.is_valid(raise_exception=True)
            validated = self._validated_query_params_cache = serializer.validated_data
        return validated

    def get_serializer_class(self):
        # This query param is set by the CSV exporter to indicate that the response should be serialized in a flat format
        if self.request.query_params.get("is_csv_export") == "1":
            return ActivityLogFlatExportSerializer

        if self._validated_query_params().get("schema") == ACTIVITY_LOG_SCHEMA_OCSF:
            return ActivityLogOCSFSerializer

        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_values"] = bool(self._validated_query_params().get("include_values"))
        return context

    @extend_schema(parameters=[AdvancedActivityLogFiltersSerializer])
    def list(self, request, *args, **kwargs):
        filters = self._validated_query_params()

        queryset = self.get_queryset()
        queryset = self.filter_manager.apply_filters(queryset, filters)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(responses={200: AvailableFiltersResponseSerializer})
    @action(detail=False, methods=["GET"])
    def available_filters(self, request, **kwargs):
        queryset = self.get_queryset()
        available_filters = self.field_discovery.get_available_filters(queryset)
        return Response(available_filters)

    @action(detail=False, methods=["POST"], required_scopes=["activity_log:read"])
    def export(self, request, **kwargs):
        export_format = request.data.get("format", "csv")

        format_mapping = {
            "csv": ExportedAsset.ExportFormat.CSV,
            "xlsx": ExportedAsset.ExportFormat.XLSX,
        }

        if export_format not in format_mapping:
            return Response({"error": f"Unsupported export format: {export_format}"}, status=400)

        filters_serializer = AdvancedActivityLogFiltersSerializer(data=request.data.get("filters", {}))

        if not filters_serializer.is_valid():
            return Response({"error": "Filters are invalid"}, status=400)

        query_params = {}

        # Transform body params to query params to include the filters in the export path
        for key, value in filters_serializer.validated_data.items():
            if value:
                if isinstance(value, list):
                    query_params[key] = ",".join(str(v) for v in value)
                elif isinstance(value, dict):
                    query_params[key] = json.dumps(value)
                else:
                    query_params[key] = str(value)

        try:
            serializable_filters = self._make_filters_serializable(filters_serializer.validated_data)
            filename = self._generate_export_filename(serializable_filters, export_format)
            source_authentication = get_export_source_authentication(request.successful_authenticator)
            if source_authentication is None:
                return Response(
                    {"error": "Exports from API endpoints do not support this authentication method."},
                    status=400,
                )

            exported_asset = ExportedAsset.objects.create(
                team=self.team,
                export_format=format_mapping[export_format],
                export_context={
                    "path": f"/api/projects/{self.team_id}/advanced_activity_logs/?{urlencode(query_params)}",
                    "method": "GET",
                    "filters": serializable_filters,
                    "filename": filename,
                },
                created_by=request.user,
                **source_authentication,
            )

            exporter.export_asset.delay(exported_asset.id)

            return Response(
                {
                    "id": exported_asset.id,
                    "export_format": export_format,
                },
                status=202,
            )

        except Exception as e:
            self.logger.exception(f"Failed to create export: {e}")
            capture_exception(e)
            return Response({"error": "Failed to create export"}, status=500)


class OrganizationActivityLogPermission(BasePermission):
    """
    Restrict the organization-scoped activity logs endpoint to organization admins and owners.

    Used in addition to OrganizationMemberPermissions, which TeamAndOrgViewSetMixin adds for
    org-nested viewsets (so we already know the user is in the organization).
    """

    message = "Only organization admins and owners can view organization-wide activity logs."

    def has_permission(self, request: Request, view) -> bool:
        try:
            organization = view.organization
        except (Organization.DoesNotExist, ValueError):
            return False

        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            return False

        return membership.level >= OrganizationMembership.Level.ADMIN


@extend_schema(tags=["activity_logs"], extensions={"x-product": "platform_features"})
class OrganizationAdvancedActivityLogsViewSet(AdvancedActivityLogsViewSet):
    """
    Organization-wide view of activity logs across every project in the organization.

    Mounted at /api/organizations/<organization_id>/advanced_activity_logs/.
    Restricted to organization admins and owners.
    """

    permission_classes = [PremiumFeaturePermission, OrganizationActivityLogPermission]
    # The parent declares {"project_id": "team_id"} but our nested route only carries
    # organization_id, so the rewrite would KeyError on missing "project_id". Reset it.
    filter_rewrite_rules: dict[str, str] = {}

    def _should_skip_parents_filter(self) -> bool:
        # parents_query_dict is {"organization_id": <uuid>} on this nested route, so let
        # TeamAndOrgViewSetMixin filter the queryset by organization_id automatically.
        return False

    def safely_get_queryset(self, queryset) -> QuerySet:
        queryset = queryset.select_related("user")

        lookback_date = get_activity_log_lookback_restriction(self.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        queryset = apply_activity_visibility_restrictions(queryset, self.request.user)
        # Org route: no single team_id (this endpoint is org-nested), so use the org-wide variant.
        queryset = restrict_loop_activity_for_org(queryset, self.organization.id, self.request.user)
        queryset = restrict_canvas_activity_for_org(queryset, self.organization.id, self.request.user)

        return queryset.order_by(*activity_log_ordering(self.request))

    @action(detail=False, methods=["POST"])
    def export(self, request, **kwargs):  # type: ignore[override]
        # Override the parent's export action: it depends on self.team (for ExportedAsset.team)
        # which is not available on org-nested routes. Defer export support until we have an
        # org-aware ExportedAsset story.
        return Response(
            {"error": "Export is not yet supported on the organization-scoped activity logs endpoint."},
            status=400,
        )
