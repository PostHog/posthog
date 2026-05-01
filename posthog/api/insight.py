import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Union, cast

from django.db import transaction
from django.db.models import Count, Exists, F, Max, OuterRef, Prefetch, QuerySet
from django.db.models.query_utils import Q
from django.http import HttpResponse
from django.utils.text import slugify
from django.utils.timezone import now

import structlog
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema_view
from loginas.utils import is_impersonated_session
from opentelemetry import trace
from prometheus_client import Counter
from pydantic import (
    BaseModel,
    Field as PydanticField,
    RootModel,
    ValidationError as PydanticValidationError,
)
from rest_framework import relations, request, serializers, status, viewsets
from rest_framework.exceptions import APIException, ParseError, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ProductKey, QueryStatus

from posthog.hogql.constants import BREAKDOWN_VALUES_LIMIT
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog import schema
from posthog.api.documentation import extend_schema, extend_schema_field, extend_schema_serializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight_metadata import generate_insight_metadata
from posthog.api.insight_suggestions import get_insight_analysis, get_insight_suggestions
from posthog.api.insight_variable import map_stale_to_latest
from posthog.api.monitoring import Feature, monitor
from posthog.api.query_coalescer import QueryCoalescingMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.services.query import process_query_dict, process_query_model
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action, format_paginated_url
from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication
from posthog.caching.fetch_from_cache import InsightResult, fetch_cached_response_by_key
from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import AccessMethod, tags_context
from posthog.constants import INSIGHT
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import get_request_analytics_properties, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default
from posthog.hogql_queries.apply_dashboard_filters import (
    WRAPPER_NODE_KINDS,
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.hogql_queries.legacy_compatibility.feature_flag import get_query_method, hogql_insights_replace_filters
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.query_runner import (
    BLOCKING_EXECUTION_MODES,
    ExecutionMode,
    execution_mode_from_refresh,
    shared_insights_execution_mode,
)
from posthog.kafka_client.topics import KAFKA_METRICS_TIME_TO_SEE_DATA
from posthog.models import Cohort, Filter, Insight, User
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    changes_between,
    describe_change,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.alert import AlertConfiguration
from posthog.models.filters.utils import get_filter
from posthog.models.insight import InsightViewed
from posthog.models.insight_caching_state import InsightCachingState
from posthog.models.insight_variable import InsightVariable
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlError, UserAccessControlSerializerMixin
from posthog.resource_limits import LimitKey, check_count_limit
from posthog.schema_migrations.upgrade import upgrade
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.settings import CAPTURE_TIME_TO_SEE_DATA, SITE_URL
from posthog.user_permissions import UserPermissionsSerializerMixin
from posthog.utils import (
    filters_override_requested_by_client,
    refresh_requested_by_client,
    relative_date_parse,
    str_to_bool,
    tile_filters_override_requested_by_client,
    variables_override_requested_by_client,
)

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

from common.hogvm.python.utils import HogVMException

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

LEGACY_INSIGHT_ENDPOINTS_BLOCKED_FLAG = "legacy-insight-endpoints-disabled"
LEGACY_INSIGHT_FILTERS_BLOCKED_FLAG = "legacy-insight-filters-disabled"


EXPORT_QUERY_CACHE_MISS = Counter(
    "export_query_cache_miss",
    "Cache misses during PNG export rendering when expected cache key was not found",
)


def _get_insight_type(insight: Insight) -> str:
    """Return a normalized lowercase insight type string for analytics."""
    if insight.query:
        # New query-based insight — source kind looks like "TrendsQuery", "FunnelsQuery", etc.
        source = insight.query.get("source", insight.query)
        kind = source.get("kind", "")
        return kind.replace("Query", "").lower() if kind else "json"
    # Legacy filter-based insight
    return str(insight.filters.get("insight", "TRENDS")).lower()


def log_and_report_insight_activity(
    *,
    activity: str,
    insight: Insight,
    insight_id: int,
    insight_short_id: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    was_impersonated: bool,
    request: Request | None = None,
    changes: list[Change] | None = None,
) -> None:
    """
    Insight id and short_id are passed separately as some activities (like delete) alter the Insight instance

    The experiments feature creates insights without a name, this does not log those
    """
    insight_name: str | None = insight.name if insight.name else insight.derived_name
    if insight_name:
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=insight_id,
            scope="Insight",
            activity=activity,
            detail=Detail(name=insight_name, changes=changes, short_id=insight_short_id),
        )
        organization = Organization.objects.get(id=organization_id)
        team = Team.objects.get(id=team_id)
        if not was_impersonated:
            report_user_action(
                user,
                f"insight {activity}",
                {"insight_id": insight_short_id},
                team=team,
                organization=organization,
                request=request,
            )


def is_legacy_insight_endpoint_blocked(user: Any, team: Team) -> bool:
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    return posthoganalytics.feature_enabled(
        LEGACY_INSIGHT_ENDPOINTS_BLOCKED_FLAG,
        str(distinct_id),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def is_legacy_insight_filters_blocked(user: Any, team: Team) -> bool:
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    return posthoganalytics.feature_enabled(
        LEGACY_INSIGHT_FILTERS_BLOCKED_FLAG,
        str(distinct_id),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def capture_legacy_api_call(request: request.Request, team: Team) -> None:
    if is_legacy_insight_endpoint_blocked(request.user, team):
        raise PermissionDenied("Legacy insight endpoints are not available for this user.")

    try:
        properties = {
            "path": request._request.path,
            "method": request._request.method,
            "query_method": get_query_method(request=request, team=team),
            "filter": get_filter(request=request, team=team),
            "user_agent": request.headers.get("user-agent"),
        }

        report_user_action(
            request.user,
            "legacy insight endpoint called",
            properties,
            team=team,
            organization=team.organization,
            request=request,
        )
    except Exception as e:
        logging.exception(f"Error in capture_legacy_api_call: {e}")
        pass


class QuerySchemaParser(JSONParser):
    """
    A query schema parser that only parses the query field and validates it against the schema if it is present

    If there is no query field this parser is a no-op
    """

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        try:
            query = data.get("query", None)
            if query:
                schema.QuerySchemaRoot.model_validate(query)
        except Exception as error:
            raise ParseError(detail=str(error))
        else:
            return data


class _DashboardsFromTilesManyField(serializers.ManyRelatedField):
    def get_attribute(self, instance: Insight) -> list[int]:
        return [tile.dashboard_id for tile in instance.dashboard_tiles.all()]

    def to_representation(self, iterable: Sequence[Any]) -> list[Any]:
        return list(iterable)


class TeamScopedDashboardsField(TeamScopedPrimaryKeyRelatedField):
    @classmethod
    def many_init(cls, *args, **kwargs):
        list_kwargs: dict[str, Any] = {"child_relation": cls(*args, **kwargs)}
        for key in kwargs:
            if key in relations.MANY_RELATION_KWARGS:
                list_kwargs[key] = kwargs[key]
        return _DashboardsFromTilesManyField(**list_kwargs)


class DashboardTileBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardTile
        fields = ["id", "dashboard_id", "deleted"]


@extend_schema_serializer(exclude_fields=["filters", "saved"])
class InsightBasicSerializer(
    TaggedItemSerializerMixin,
    UserPermissionsSerializerMixin,
    serializers.ModelSerializer,
    UserAccessControlSerializerMixin,
):
    """
    Simplified serializer to speed response times when loading large amounts of objects.
    """

    dashboard_tiles = DashboardTileBasicSerializer(many=True, read_only=True)
    dashboards = serializers.SerializerMethodField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    last_viewed_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "derived_name",
            "filters",
            "query",
            "dashboards",
            "dashboard_tiles",
            "description",
            "last_refresh",
            "refreshing",
            "saved",
            "tags",
            "updated_at",
            "created_by",
            "created_at",
            "last_modified_at",
            "favorited",
            "user_access_level",
            "last_viewed_at",
        ]
        read_only_fields = ("short_id", "updated_at", "last_refresh", "refreshing")

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_dashboards(self, instance: Insight) -> list[int]:
        return [tile.dashboard_id for tile in instance.dashboard_tiles.all()]

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_viewed_at(self, instance: Insight):
        """Get the last viewed timestamp for this insight by any user in the team."""
        return getattr(instance, "last_viewed_at", None)

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        if hogql_insights_replace_filters(instance.team) and (
            instance.query is not None or instance.query_from_filters is not None
        ):
            representation["filters"] = {}
            representation["query"] = instance.query or instance.query_from_filters
        else:
            filters = instance.dashboard_filters()
            representation["filters"] = filters

        # upgrade the query to the latest version
        representation["query"] = upgrade(representation["query"])

        return representation

    @lru_cache(maxsize=1)  # noqa: B019 - short-lived serializer
    def _dashboard_tiles(self, instance):
        return [tile.dashboard_id for tile in instance.dashboard_tiles.all()]


class _InsightQuerySchema(RootModel):
    """The query definition for this insight. The `kind` field determines the query type:
    - `InsightVizNode` — product analytics (trends, funnels, retention, paths, stickiness, lifecycle)
    - `DataVisualizationNode` — SQL insights using HogQL
    - `DataTableNode` — raw data tables
    - `HogQuery` — Hog language queries
    """

    root: schema.InsightVizNode | schema.DataTableNode | schema.DataVisualizationNode | schema.HogQuery = PydanticField(
        discriminator="kind"
    )


@extend_schema_field(_InsightQuerySchema)  # type: ignore[arg-type]
class QueryFieldSerializer(serializers.Serializer):
    def to_representation(self, value):
        return self.parent._query_variables_mapping(value)  # type: ignore

    def to_internal_value(self, data):
        if data is not None and not isinstance(data, dict):
            raise serializers.ValidationError("Query must be a valid JSON object")
        return data


def _last_refresh_for_shared_gate(insight: Insight, dashboard_tile: DashboardTile | None) -> datetime | None:
    """Throttle clock for `?refresh=force_blocking` on shared insights. On DB error, returns
    ``now()`` so the gate fails closed."""
    try:
        if dashboard_tile is not None:
            cs = next(iter(dashboard_tile.caching_states.all()), None)
        else:
            cs = (
                InsightCachingState.objects.filter(insight=insight, dashboard_tile=None)
                .only("last_refresh", "created_at")
                .first()
            )
    except Exception:
        return datetime.now(UTC)
    if cs is None:
        return insight.created_at
    return cs.last_refresh or cs.created_at


class InsightSerializer(InsightBasicSerializer):
    result = serializers.SerializerMethodField()
    hasMore = serializers.SerializerMethodField()
    columns = serializers.SerializerMethodField()
    last_refresh = serializers.SerializerMethodField(
        read_only=True,
        help_text="""
    The datetime this insight's results were generated.
    If added to one or more dashboards the insight can be refreshed separately on each.
    Returns the appropriate last_refresh datetime for the context the insight is viewed in
    (see from_dashboard query parameter).
    """,
    )
    cache_target_age = serializers.SerializerMethodField(
        read_only=True,
        help_text="The target age of the cached results for this insight.",
    )
    next_allowed_client_refresh = serializers.SerializerMethodField(
        read_only=True,
        help_text="""
    The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
    by querying the database.
    """,
    )
    is_cached = serializers.SerializerMethodField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    effective_restriction_level = serializers.SerializerMethodField()
    effective_privilege_level = serializers.SerializerMethodField()
    timezone = serializers.SerializerMethodField(help_text="The timezone this chart is displayed in.")
    last_viewed_at = serializers.SerializerMethodField(read_only=True)
    dashboards = TeamScopedDashboardsField(  # type: ignore[assignment]
        help_text="""
        DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
        A dashboard ID for each of the dashboards that this insight is displayed on.
        """,
        many=True,
        required=False,
        queryset=Dashboard.objects.all(),
    )
    dashboard_tiles = DashboardTileBasicSerializer(
        many=True,
        read_only=True,
        help_text="""
    A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
    """,
    )
    query = QueryFieldSerializer(required=False, allow_null=True)
    query_status = serializers.SerializerMethodField()
    hogql = serializers.SerializerMethodField()
    types = serializers.SerializerMethodField()
    resolved_date_range = serializers.SerializerMethodField(read_only=True)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    alerts = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "derived_name",
            "filters",
            "query",
            "order",
            "deleted",
            "dashboards",
            "dashboard_tiles",
            "last_refresh",
            "cache_target_age",
            "next_allowed_client_refresh",
            "result",
            "hasMore",
            "columns",
            "created_at",
            "created_by",
            "description",
            "updated_at",
            "tags",
            "favorited",
            "saved",
            "last_modified_at",
            "last_modified_by",
            "is_sample",
            "effective_restriction_level",
            "effective_privilege_level",
            "user_access_level",
            "timezone",
            "is_cached",
            "query_status",
            "hogql",
            "types",
            "resolved_date_range",
            "_create_in_folder",
            "alerts",
            "last_viewed_at",
        ]
        read_only_fields = (
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "short_id",
            "updated_at",
            "is_sample",
            "effective_restriction_level",
            "effective_privilege_level",
            "user_access_level",
            "timezone",
            "refreshing",
            "is_cached",
        )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        query = attrs.get("query") if "query" in attrs else None
        using_legacy_filters = "filters" in attrs and attrs.get("filters") is not None and query in (None, {})
        if using_legacy_filters and is_legacy_insight_filters_blocked(
            self.context["request"].user, self.context["get_team"]()
        ):
            raise PermissionDenied("Creating or updating insights with legacy filters is not available for this user.")

        new_dashboards = attrs.get("dashboards")
        if new_dashboards is not None:
            team = self.context["get_team"]()
            existing_dashboard_ids: set[int] = set()
            if self.instance is not None:
                existing_dashboard_ids = set(
                    self.instance.dashboard_tiles.exclude(deleted=True).values_list("dashboard_id", flat=True)
                )
            for dashboard in new_dashboards:
                if dashboard.id in existing_dashboard_ids:
                    continue
                current_tiles = DashboardTile.objects.filter(dashboard_id=dashboard.id).exclude(deleted=True).count()
                check_count_limit(
                    team=team,
                    key=LimitKey.MAX_INSIGHTS_PER_DASHBOARD,
                    current_count=current_tiles,
                    user=self.context["request"].user,
                )

        return super().validate(attrs)

    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="POST")
    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        tags = validated_data.pop("tags", None)  # tags are created separately as global tag relationships
        team_id = self.context["team_id"]

        created_by = validated_data.pop("created_by", request.user)
        dashboards = validated_data.pop("dashboards", None)

        insight = Insight.objects.create(
            team_id=team_id,
            created_by=created_by,
            last_modified_by=request.user,
            **validated_data,
        )

        InsightViewed.objects.create(team_id=team_id, user=request.user, insight=insight, last_viewed_at=now())

        if dashboards is not None:
            # Per-dashboard limit (analytics.max_insights_per_dashboard) is enforced
            # in validate(); see InsightSerializer.validate above.
            # nosemgrep: idor-lookup-without-team
            for dashboard in Dashboard.objects.filter(id__in=[d.id for d in dashboards]).all():
                if dashboard.team != insight.team:
                    raise serializers.ValidationError("Dashboard not found")

                DashboardTile.objects.create(insight=insight, dashboard=dashboard, last_refresh=now())
                report_user_action(
                    self.context["request"].user,
                    "dashboard tile added",
                    {
                        "tile_type": "insight",
                        "insight_type": _get_insight_type(insight),
                        "dashboard_id": dashboard.id,
                    },
                    team=insight.team,
                    request=self.context["request"],
                )

        # Manual tag creation since this create method doesn't call super()
        self._attempt_set_tags(tags, insight)

        log_and_report_insight_activity(
            activity="created",
            insight=insight,
            insight_id=insight.id,
            insight_short_id=insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team_id,
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            request=self.context["request"],
        )

        return insight

    @transaction.atomic()
    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="PATCH")
    def update(self, instance: Insight, validated_data: dict, **kwargs) -> Insight:
        dashboards_before_change: list[Union[str, dict]] = []
        try:
            # since it is possible to be restoring a soft deleted insight
            # the state captured before the update has to include soft deleted insights
            # or we can't capture undeletes to the activity log
            before_update = Insight.objects_including_soft_deleted.prefetch_related(
                "tagged_items__tag", "dashboards"
            ).get(pk=instance.id)

            dashboards_before_change = [describe_change(dt.dashboard) for dt in instance.dashboard_tiles.all()]
            dashboards_before_change = sorted(
                dashboards_before_change,
                key=lambda x: -1 if isinstance(x, str) else x["id"],
            )
        except Insight.DoesNotExist:
            before_update = None

        # Remove is_sample if it's set as user has altered the sample configuration
        validated_data["is_sample"] = False

        # Legacy insights, some API callers (e.g. MCP),
        # and insights created from a template may have saved=False.
        # The saved field is a vestige of a removed "insight history" feature (2020).
        # Some functionalities (like search) depend on saved=True, so ensure any
        # update corrects this for older records.
        validated_data.setdefault("saved", True)

        if validated_data.keys() & Insight.MATERIAL_INSIGHT_FIELDS:
            instance.last_modified_at = now()
            instance.last_modified_by = self.context["request"].user

        if validated_data.get("deleted", False):
            DashboardTile.objects_including_soft_deleted.filter(insight__id=instance.id).update(deleted=True)
        else:
            dashboards = validated_data.pop("dashboards", None)
            if dashboards is not None:
                self._update_insight_dashboards(dashboards, instance)

        updated_insight = super().update(instance, validated_data)
        if not updated_insight.are_alerts_supported:
            instance.alertconfiguration_set.all().delete()

        self._log_insight_update(before_update, dashboards_before_change, updated_insight)

        self.user_permissions.reset_insights_dashboard_cached_results()

        return updated_insight

    def _log_insight_update(
        self,
        before_update,
        dashboards_before_change,
        updated_insight,
    ):
        """
        KLUDGE: Automatic detection of insight dashboard updates is flaky
        This removes any detected update from the auto-detected changes
        And adds in a synthetic change using data captured at the point dashboards are updated
        """
        detected_changes = [
            c
            for c in changes_between("Insight", previous=before_update, current=updated_insight)
            if c.field != "dashboards"
        ]
        synthetic_dashboard_changes = self._synthetic_dashboard_changes(dashboards_before_change)
        changes = detected_changes + synthetic_dashboard_changes

        activity = "updated"
        deleted_change = next((change for change in changes if change.field == "deleted"), None)
        if deleted_change:
            if bool(deleted_change.after):
                activity = "deleted"
            elif bool(deleted_change.before):
                activity = "restored"

        log_and_report_insight_activity(
            activity=activity,
            insight=updated_insight,
            insight_id=updated_insight.id,
            insight_short_id=updated_insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            request=self.context["request"],
            changes=changes,
        )

    def _synthetic_dashboard_changes(self, dashboards_before_change: list[dict]) -> list[Change]:
        artificial_dashboard_changes = self.context.get("after_dashboard_changes", [])
        if artificial_dashboard_changes:
            return [
                Change(
                    type="Insight",
                    action="changed",
                    field="dashboards",
                    before=dashboards_before_change,
                    after=artificial_dashboard_changes,
                )
            ]

        return []

    def _update_insight_dashboards(self, dashboards: list[Dashboard], instance: Insight) -> None:
        old_dashboard_ids = [tile.dashboard_id for tile in instance.dashboard_tiles.all()]
        new_dashboard_ids = [d.id for d in dashboards if not d.deleted]

        if sorted(old_dashboard_ids) == sorted(new_dashboard_ids):
            return

        ids_to_add = [id for id in new_dashboard_ids if id not in old_dashboard_ids]
        ids_to_remove = [id for id in old_dashboard_ids if id not in new_dashboard_ids]
        # nosemgrep: idor-lookup-without-team (team check after lookup)
        candidate_dashboards = Dashboard.objects.filter(id__in=ids_to_add)
        dashboard: Dashboard
        for dashboard in candidate_dashboards:
            # does this user have permission on dashboards to add... if they are restricted
            # it will mean this dashboard becomes restricted because of the patch
            if (
                self.user_permissions.dashboard(dashboard).effective_privilege_level
                != Dashboard.PrivilegeLevel.CAN_EDIT
            ):
                raise PermissionDenied(f"You don't have permission to add insights to dashboard: {dashboard.id}")

            if dashboard.team != instance.team:
                raise serializers.ValidationError("Dashboard not found")

            tile, _ = DashboardTile.objects_including_soft_deleted.get_or_create(insight=instance, dashboard=dashboard)

            if tile.deleted:
                tile.deleted = False
                tile.save()

            report_user_action(
                self.context["request"].user,
                "dashboard tile added",
                {
                    "tile_type": "insight",
                    "insight_type": _get_insight_type(instance),
                    "dashboard_id": dashboard.id,
                },
                team=instance.team,
                request=self.context["request"],
            )

        if ids_to_remove:
            # Check permission before removing insight from dashboards
            # nosemgrep: idor-lookup-without-team (team check after lookup)
            dashboards_to_remove = Dashboard.objects.filter(id__in=ids_to_remove)
            for dashboard in dashboards_to_remove:
                if (
                    self.user_permissions.dashboard(dashboard).effective_privilege_level
                    != Dashboard.PrivilegeLevel.CAN_EDIT
                ):
                    raise PermissionDenied(
                        f"You don't have permission to remove insights from dashboard: {dashboard.id}"
                    )

            DashboardTile.objects.filter(dashboard_id__in=ids_to_remove, insight=instance).update(deleted=True)

        self.context["after_dashboard_changes"] = [describe_change(d) for d in dashboards if not d.deleted]

    @extend_schema_field(OpenApiTypes.ANY)
    def get_result(self, insight: Insight):
        return self.insight_result(insight).result

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_hasMore(self, insight: Insight):
        return self.insight_result(insight).has_more

    @extend_schema_field(serializers.ListField(child=serializers.CharField(), allow_null=True))
    def get_columns(self, insight: Insight):
        return self.insight_result(insight).columns

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_timezone(self, insight: Insight):
        # :TODO: This doesn't work properly as background cache updates don't set timezone in the response.
        # This should get refactored.
        if refresh_requested_by_client(self.context["request"]):
            return insight.team.timezone

        return self.insight_result(insight).timezone

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_refresh(self, insight: Insight):
        return self.insight_result(insight).last_refresh

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_cache_target_age(self, insight: Insight):
        return self.insight_result(insight).cache_target_age

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_next_allowed_client_refresh(self, insight: Insight):
        return self.insight_result(insight).next_allowed_client_refresh

    @extend_schema_field(serializers.BooleanField())
    def get_is_cached(self, insight: Insight):
        return self.insight_result(insight).is_cached

    @extend_schema_field(OpenApiTypes.ANY)
    def get_query_status(self, insight: Insight):
        return self.insight_result(insight).query_status

    def _query_variables_mapping(self, query: dict):
        if (
            query
            and isinstance(query, dict)
            and query.get("kind") == "DataVisualizationNode"
            and query.get("source", {}).get("variables")
        ):
            query["source"]["variables"] = map_stale_to_latest(
                query["source"]["variables"], list(self.context["insight_variables"])
            )

        return query

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_hogql(self, insight: Insight):
        return self.insight_result(insight).hogql

    @extend_schema_field(serializers.ListField(allow_null=True))
    def get_types(self, insight: Insight):
        return self.insight_result(insight).types

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "date_from": {"type": "string", "format": "date-time"},
                "date_to": {"type": "string", "format": "date-time"},
            },
        }
    )
    def get_resolved_date_range(self, insight: Insight):
        return self.insight_result(insight).resolved_date_range

    @extend_schema_field(serializers.ListField())
    def get_alerts(self, insight: Insight):
        if not insight.are_alerts_supported:
            return []

        # Use prefetched alerts data
        alerts = getattr(insight, "_prefetched_alerts", [])
        from posthog.api.alert import AlertSerializer

        return AlertSerializer(alerts, many=True, context=self.context).data

    def get_effective_restriction_level(self, insight: Insight) -> Dashboard.RestrictionLevel:
        if self.context.get("is_shared"):
            return Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        return self.user_permissions.insight(insight).effective_restriction_level

    def get_effective_privilege_level(self, insight: Insight) -> Dashboard.PrivilegeLevel:
        if self.context.get("is_shared"):
            return Dashboard.PrivilegeLevel.CAN_VIEW
        return self.user_permissions.insight(insight).effective_privilege_level

    def to_representation(self, instance: Insight):
        representation = super().to_representation(instance)

        # Check if user has access to this insight when viewed in dashboard context
        if self.context.get("dashboard"):
            from posthog.rbac.user_access_control import access_level_satisfied_for_resource

            user_access_level = representation.get("user_access_level")
            if user_access_level and not access_level_satisfied_for_resource("insight", user_access_level, "viewer"):
                # User doesn't have sufficient access - return minimal insight data
                return {
                    "id": instance.id,
                    "short_id": instance.short_id,
                    "user_access_level": user_access_level,
                }

        # the ORM doesn't know about deleted dashboard tiles
        # when they have just been updated
        # we store them and can use that list to correct the response
        # and avoid refreshing from the DB
        if self.context.get("after_dashboard_changes"):
            representation["dashboards"] = [
                described_dashboard["id"] for described_dashboard in self.context["after_dashboard_changes"]
            ]

        dashboard: Dashboard | None = self.context.get("dashboard")
        request: Request | None = self.context.get("request")
        dashboard_filters_override = filters_override_requested_by_client(request, dashboard) if request else None
        dashboard_variables_override = variables_override_requested_by_client(
            request, dashboard, list(self.context["insight_variables"])
        )

        if hogql_insights_replace_filters(instance.team) and (
            instance.query is not None or instance.query_from_filters is not None
        ):
            query = instance.query or instance.query_from_filters
            if (
                dashboard is not None
                or dashboard_filters_override is not None
                or dashboard_variables_override is not None
            ):
                query = apply_dashboard_filters_to_dict(
                    query,
                    (
                        dashboard_filters_override
                        if dashboard_filters_override is not None
                        else dashboard.filters
                        if dashboard
                        else {}
                    ),
                    instance.team,
                )

                query = apply_dashboard_variables_to_dict(
                    query,
                    dashboard_variables_override or {},
                    instance.team,
                )
            representation["filters"] = {}
            representation["query"] = query
        else:
            representation["filters"] = instance.dashboard_filters(
                dashboard=dashboard, dashboard_filters_override=dashboard_filters_override
            )
            representation["query"] = instance.get_effective_query(
                dashboard=dashboard,
                dashboard_filters_override=dashboard_filters_override,
                dashboard_variables_override=dashboard_variables_override,
            )

            if "insight" not in representation["filters"] and not representation["query"]:
                representation["filters"]["insight"] = "TRENDS"

        representation["filters_hash"] = self.insight_result(instance).cache_key

        # Hide PII fields when hideExtraDetails from SharingConfiguration is enabled
        if self.context.get("hide_extra_details", False):
            representation.pop("created_by", None)
            representation.pop("last_modified_by", None)
            representation.pop("created_at", None)
            representation.pop("last_modified_at", None)

        return representation

    @lru_cache(maxsize=1)  # noqa: B019 - short-lived serializer
    def insight_result(self, insight: Insight) -> InsightResult:
        from posthog.caching.calculate_results import calculate_for_query_based_insight

        dashboard: Dashboard | None = self.context.get("dashboard")

        # Check if we have an expected cache key from the image exporter
        export_cache_keys: dict[int, str] | None = self.context.get("export_cache_keys")
        if export_cache_keys and insight.id in export_cache_keys:
            expected_cache_key = export_cache_keys[insight.id]
            cached_response = fetch_cached_response_by_key(expected_cache_key, team_id=insight.team_id)
            if cached_response:
                return InsightResult(
                    result=cached_response.get("results"),
                    has_more=cached_response.get("hasMore"),
                    columns=cached_response.get("columns"),
                    last_refresh=cached_response.get("last_refresh"),
                    cache_key=expected_cache_key,
                    is_cached=True,
                    timezone=cached_response.get("timezone"),
                    next_allowed_client_refresh=cached_response.get("next_allowed_client_refresh"),
                    cache_target_age=cached_response.get("cache_target_age"),
                    timings=cached_response.get("timings"),
                    query_status=cached_response.get("query_status"),
                    hogql=cached_response.get("hogql"),
                    types=cached_response.get("types"),
                )
            else:
                EXPORT_QUERY_CACHE_MISS.inc()
                logger.error(
                    "export_cache_key_miss",
                    insight_id=insight.id,
                    expected_cache_key=expected_cache_key,
                    message="Expected cache key not found during export - falling back to normal calculation",
                )

        with upgrade_query(insight):
            try:
                refresh_requested = refresh_requested_by_client(self.context["request"])
                execution_mode = execution_mode_from_refresh(refresh_requested)
                filters_override = filters_override_requested_by_client(self.context["request"], dashboard)
                variables_override = variables_override_requested_by_client(
                    self.context["request"], dashboard, list(self.context["insight_variables"])
                )

                dashboard_tile = self.dashboard_tile_from_context(insight, dashboard)
                tile_filters_override = tile_filters_override_requested_by_client(
                    self.context["request"], dashboard_tile
                )

                is_shared = self.context.get("is_shared", False)
                if is_shared:
                    execution_mode = shared_insights_execution_mode(
                        execution_mode,
                        last_refresh=_last_refresh_for_shared_gate(insight, dashboard_tile),
                    )

                # Shared rendering bypasses the FE scene-tag flow, so set product/feature
                # tags here. No-op overwrite for authenticated paths (same values).
                shared_tags = {"access_method": AccessMethod.SHARING_TOKEN} if is_shared else {}
                with tags_context(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, **shared_tags):
                    return calculate_for_query_based_insight(
                        insight,
                        team=self.context["get_team"](),
                        dashboard=dashboard,
                        execution_mode=execution_mode,
                        user=None if self.context["request"].user.is_anonymous else self.context["request"].user,
                        filters_override=filters_override,
                        variables_override=variables_override,
                        tile_filters_override=tile_filters_override,
                        analytics_props=get_request_analytics_properties(self.context["request"]),
                    )
            except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
                raise ValidationError(str(e), getattr(e, "code_name", None))
            except ConcurrencyLimitExceeded as e:
                logger.warn(
                    "concurrency_limit_exceeded_api", exception=e, insight_id=insight.id, team_id=insight.team_id
                )
                return InsightResult(
                    result=None,
                    last_refresh=now(),
                    is_cached=False,
                    query_status=dict(
                        QueryStatus(
                            id=self.context["request"].query_params.get("client_query_id"),
                            team_id=insight.team_id,
                            insight_id=str(insight.id),
                            dashboard_id=str(dashboard.id) if dashboard else None,
                            error_message="concurrency_limit_exceeded",
                            error=True,
                        )
                    ),
                    cache_key=None,
                    hogql=None,
                    columns=None,
                    has_more=None,
                    timezone=self.context["get_team"]().timezone,
                )
            except Exception as e:
                # Capture unexpected crashes so the API list doesn't fail
                logger.exception("insight_calculation_error", insight_id=insight.id, team_id=insight.team_id)
                return InsightResult(
                    result=None,
                    last_refresh=None,
                    is_cached=False,
                    query_status=dict(
                        QueryStatus(
                            id=self.context["request"].query_params.get("client_query_id"),
                            team_id=insight.team_id,
                            insight_id=str(insight.id),
                            dashboard_id=str(dashboard.id) if dashboard else None,
                            error_message=str(e),
                            error=True,
                        )
                    ),
                    cache_key=None,
                    hogql=None,
                    columns=None,
                    has_more=None,
                    timezone=self.context["get_team"]().timezone,
                )

    @lru_cache(maxsize=1)  # noqa: B019 - short-lived serializer, one insight/tile combo
    def dashboard_tile_from_context(self, insight: Insight, dashboard: Dashboard | None) -> DashboardTile | None:
        dashboard_tile: DashboardTile | None = self.context.get("dashboard_tile", None)

        if dashboard_tile and dashboard_tile.deleted:
            self.context.update({"dashboard_tile": None})
            dashboard_tile = None

        if not dashboard_tile and dashboard:
            dashboard_tile = DashboardTile.dashboard_queryset(
                DashboardTile.objects.filter(insight=insight, dashboard=dashboard)
            ).first()

        return dashboard_tile


class MCPInsightSerializer(InsightSerializer):
    """Serializer for MCP insight create/update requests.

    Accepts raw product analytics queries and normalizes them into the correct saved-insight
    wrapper before persisting: HogQLQuery → DataVisualizationNode, insight queries
    (TrendsQuery, FunnelsQuery, PathsQuery) → InsightVizNode.
    """

    query = QueryFieldSerializer(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.context["view"].action == "create" and "query" not in attrs:
            raise serializers.ValidationError({"query": "This field is required."})
        return super().validate(attrs)

    def validate_query(self, value: dict[str, Any]) -> dict[str, Any]:
        # Raw HogQL → DataVisualizationNode
        try:
            return schema.DataVisualizationNode(source=schema.HogQLQuery.model_validate(value)).model_dump(
                exclude_none=True, mode="json"
            )
        except PydanticValidationError:
            pass

        # Already-wrapped node → use as-is
        for wrapped_cls in (schema.DataVisualizationNode, schema.InsightVizNode):
            try:
                return wrapped_cls.model_validate(value).model_dump(exclude_none=True, mode="json")
            except PydanticValidationError:
                pass

        # Raw product analytics query → InsightVizNode
        try:
            return schema.InsightVizNode.model_validate({"kind": "InsightVizNode", "source": value}).model_dump(
                exclude_none=True, mode="json"
            )
        except PydanticValidationError as exc:
            details = "; ".join(f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise serializers.ValidationError(f"This query can't be saved: {details}")


# Insights can be looked up by either the numeric primary key or the 8-character `short_id`
# (the alphanumeric code visible in URLs like `/insights/AaVQ8Ijw`). The resolution happens in
# `InsightViewSet.safely_get_object`: a purely-numeric string is treated as the PK, otherwise it
# falls back to `short_id`. Advertise both forms in the OpenAPI schema so generated clients
# (frontend, MCP tools) do not constrain callers to integers.
INSIGHT_ID_PATH_PARAMETER = OpenApiParameter(
    name="id",
    location=OpenApiParameter.PATH,
    type={"oneOf": [{"type": "integer"}, {"type": "string"}]},
    description="Numeric primary key or 8-character `short_id` (for example `AaVQ8Ijw`) identifying the insight.",
)


@extend_schema(tags=[ProductKey.PRODUCT_ANALYTICS])
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="refresh",
                enum=list(ExecutionMode),
                default=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                # Sync the `refresh` description here with the other one in this file, and with frontend/src/queries/schema.ts
                description="""
Whether to refresh the retrieved insights, how aggressively, and if sync or async:
- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
- `'force_blocking'` - calculate synchronously, even if fresh results are already cached
- `'force_async'` - kick off background calculation, even if fresh results are already cached
Background calculation can be tracked using the `query_status` response field.""",
            ),
            OpenApiParameter(
                name="basic",
                type=OpenApiTypes.BOOL,
                description="Return basic insight metadata only (no results, faster).",
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                description="Case-insensitive substring match across name, derived_name, description, and tag names.",
            ),
            OpenApiParameter(
                name="created_by",
                type=OpenApiTypes.STR,
                description="JSON-encoded array of user IDs. Only returns insights whose `created_by` is in the list, e.g. `[1,42]`.",
            ),
            OpenApiParameter(
                name="user",
                type=OpenApiTypes.BOOL,
                description="Include this parameter (any value) to restrict results to insights created by the authenticated user.",
            ),
            OpenApiParameter(
                name="favorited",
                type=OpenApiTypes.BOOL,
                description="Include this parameter (any value) to restrict results to insights marked as favorited.",
            ),
            OpenApiParameter(
                name="saved",
                type=OpenApiTypes.BOOL,
                description="When truthy, restricts results to insights that are saved (or attached to a visible dashboard). When falsy, only unsaved insights.",
            ),
            OpenApiParameter(
                name="insight",
                enum=["TRENDS", "FUNNELS", "RETENTION", "PATHS", "STICKINESS", "LIFECYCLE", "JSON", "SQL"],
                description="Restrict to a single insight type. `JSON` matches non-wrapper query insights; `SQL` matches HogQL queries.",
            ),
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.STR,
                description="Filter by `last_modified_at > date_from`. Accepts absolute dates (`2025-04-23`) or relative strings (`-7d`, `-1m`).",
            ),
            OpenApiParameter(
                name="date_to",
                type=OpenApiTypes.STR,
                description="Filter by `last_modified_at < date_to`. Accepts absolute dates or relative strings.",
            ),
            OpenApiParameter(
                name="created_date_from",
                type=OpenApiTypes.STR,
                description="Filter by `created_at > created_date_from`. Accepts absolute or relative dates.",
            ),
            OpenApiParameter(
                name="created_date_to",
                type=OpenApiTypes.STR,
                description="Filter by `created_at < created_date_to`. Accepts absolute or relative dates.",
            ),
            OpenApiParameter(
                name="last_viewed_date_from",
                type=OpenApiTypes.STR,
                description="Filter by `last_viewed_at > last_viewed_date_from`. Accepts absolute or relative dates.",
            ),
            OpenApiParameter(
                name="last_viewed_date_to",
                type=OpenApiTypes.STR,
                description="Filter by `last_viewed_at < last_viewed_date_to`. Accepts absolute or relative dates.",
            ),
            OpenApiParameter(
                name="dashboards",
                type=OpenApiTypes.STR,
                description="JSON-encoded array of dashboard IDs. Returns insights attached to every listed dashboard (AND).",
            ),
            OpenApiParameter(
                name="tags",
                type=OpenApiTypes.STR,
                description="JSON-encoded array of tag names. Returns insights with any of the listed tags.",
            ),
        ]
    ),
    update=extend_schema(parameters=[INSIGHT_ID_PATH_PARAMETER]),
    partial_update=extend_schema(parameters=[INSIGHT_ID_PATH_PARAMETER]),
    destroy=extend_schema(parameters=[INSIGHT_ID_PATH_PARAMETER]),
)
class InsightViewSet(
    QueryCoalescingMixin,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "insight"
    serializer_class = InsightSerializer
    throttle_classes = [
        ClickHouseBurstRateThrottle,
        ClickHouseSustainedRateThrottle,
    ]
    renderer_classes = cast(
        tuple[type[BaseRenderer], ...],
        (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.CSVRenderer),
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    sharing_enabled_actions = ["retrieve", "list"]
    queryset = Insight.objects_including_soft_deleted.all()

    parser_classes = (QuerySchemaParser,)

    def get_throttles(self):
        """Apply LLM-specific throttles to AI analysis endpoints."""
        if self.action in ["analyze", "suggestions", "generate_metadata"]:
            return [
                LLMAnalyticsSummarizationBurstThrottle(),
                LLMAnalyticsSummarizationSustainedThrottle(),
                LLMAnalyticsSummarizationDailyThrottle(),
            ]
        return super().get_throttles()

    def _validate_ai_feature_access(self) -> None:
        """Validate that AI data processing is approved by the organization."""
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization")

    @staticmethod
    def _is_mcp_request(request: Request) -> bool:
        return request.headers.get("x-posthog-client") == "mcp"

    def _is_basic_request(self) -> bool:
        return self.action in ("list", "retrieve") and str_to_bool(self.request.query_params.get("basic", "0"))

    @tracer.start_as_current_span("insight_api_list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        span = trace.get_current_span()
        span.set_attribute("posthog.team_id", self.team_id)
        span.set_attribute("posthog.basic", self._is_basic_request())
        span.set_attribute("posthog.saved", str_to_bool(request.query_params.get("saved", "0")))
        span.set_attribute("posthog.order", request.query_params.get("order", ""))
        return super().list(request, *args, **kwargs)

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if (
            page is not None
            and getattr(self, "action", None) == "list"
            and not self._is_basic_request()
            and not isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication)
        ):
            tiles = [tile for insight in page for tile in insight.dashboard_tiles.all()]
            self.user_permissions.set_preloaded_dashboard_tiles(tiles)
        return page

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self._is_basic_request():
            return InsightBasicSerializer
        if self.action in ("create", "partial_update") and self._is_mcp_request(self.request):
            return MCPInsightSerializer
        return super().get_serializer_class()

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()

        context["is_shared"] = isinstance(
            self.request.successful_authenticator,
            SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication,
        )
        context["insight_variables"] = InsightVariable.objects.filter(team=self.team).all()

        return context

    def dangerously_get_queryset(self):
        # Insights are retrieved under /environments/ because they include team-specific query results,
        # but they are in fact project-level, rather than environment-level
        assert self.team.project_id is not None
        queryset = self.queryset.filter(team__project_id=self.team.project_id)

        include_deleted = False

        if isinstance(
            self.request.successful_authenticator,
            SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication,
        ):
            queryset = queryset.filter(
                id__in=self.request.successful_authenticator.sharing_configuration.get_connected_insight_ids()
            )
        elif self.action == "partial_update" and self.request.data.get("deleted") is False:
            # an insight can be restored by patching {"deleted": False}
            include_deleted = True

        if not include_deleted:
            queryset = queryset.exclude(deleted=True)

        # InsightBasicSerializer skips alerts and only needs PKs from dashboards plus
        # (id, dashboard_id, deleted) from tiles, so the heavy team→organization joins
        # the full serializer relies on are pure waste on the basic path.
        is_basic = self._is_basic_request()

        if is_basic:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "dashboard_tiles",
                    queryset=DashboardTile.objects.only("id", "dashboard_id", "deleted", "insight_id"),
                ),
            )
        else:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "dashboard_tiles",
                    queryset=DashboardTile.objects.select_related("dashboard__team__organization"),
                ),
                Prefetch(
                    "alertconfiguration_set",
                    queryset=AlertConfiguration.objects.select_related("created_by"),
                    to_attr="_prefetched_alerts",
                ),
            )

        # Add access level filtering for list actions if not sharing access token
        if not isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication):
            queryset = self._filter_queryset_by_access_level(queryset)

        if is_basic:
            queryset = queryset.select_related("created_by", "team")
        else:
            queryset = queryset.select_related("created_by", "last_modified_by", "team")

        if self.action == "list":
            queryset = queryset.prefetch_related("tagged_items__tag")
            queryset = queryset.annotate(last_viewed_at=Max("insightviewed__last_viewed_at"))
            queryset = self._filter_request(self.request, queryset)

        return self.order_queryset(queryset)

    def safely_get_object(self, queryset: QuerySet) -> Insight | None:
        lookup_value = self.kwargs[self.lookup_field]
        if isinstance(lookup_value, str) and lookup_value.isdigit():
            # A numeric lookup is ambiguous: usually it's a primary key, but a small number of
            # legacy rows have numeric-only short_ids. Try pk first (preserving existing behavior)
            # and fall back to short_id so those legacy insights stay retrievable.
            pk_match = queryset.filter(pk=int(lookup_value)).first()
            if pk_match is not None:
                return pk_match
        return queryset.filter(short_id=lookup_value).first()

    def order_queryset(self, queryset: QuerySet) -> QuerySet:
        order = self.request.GET.get("order", None)
        if not order:
            return queryset.order_by("order")

        if order == "-last_viewed_at":
            return queryset.order_by(F("last_viewed_at").desc(nulls_last=True))

        if order == "last_viewed_at":
            return queryset.order_by(F("last_viewed_at").asc(nulls_first=True))

        return queryset.order_by(order)

    @action(methods=["GET"], detail=False)
    def my_last_viewed(self, request: request.Request, *args, **kwargs) -> Response:
        """
        Returns basic details about the last 5 insights viewed by this user. Most recently viewed first.
        """
        insight_queryset = (
            InsightViewed.objects.filter(team=self.team, user=cast(User, request.user))
            .select_related("insight")
            .exclude(insight__deleted=True)
            .only("insight", "last_viewed_at")
        )

        recently_viewed = []
        for rv in insight_queryset.order_by("-last_viewed_at")[:5]:
            insight = rv.insight
            insight.last_viewed_at = rv.last_viewed_at  # type: ignore
            recently_viewed.append(insight)

        response = InsightBasicSerializer(recently_viewed, many=True)
        return Response(data=response.data, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False)
    def trending(self, request: request.Request, *args, **kwargs) -> Response:
        """
        Returns trending insights based on view count in the last N days (default 7).
        Defaults to returning top 10 insights.
        """
        try:
            days = int(request.GET.get("days", "1"))
            limit = min(int(request.GET.get("limit", "10")), 100)
        except (ValueError, TypeError):
            raise ValidationError("days and limit must be valid integers")

        cutoff_date = now() - timedelta(days=days)

        queryset = (
            Insight.objects.filter(team__project_id=self.team.project_id)
            .annotate(
                view_count=Count(
                    "insightviewed",
                    filter=Q(insightviewed__last_viewed_at__gte=cutoff_date),
                )
            )
            .filter(view_count__gt=0)
            .order_by("-view_count", "-last_modified_at")
        )

        queryset = self._filter_queryset_by_access_level(queryset)
        queryset = queryset[:limit]
        queryset = queryset.annotate(last_viewed_at=Max("insightviewed__last_viewed_at"))

        response = InsightBasicSerializer(queryset, many=True)
        data = response.data

        # Batch fetch all viewers to avoid N+1 queries
        insight_ids = [item["id"] for item in data]
        all_viewers = (
            InsightViewed.objects.filter(
                team=self.team,
                insight_id__in=insight_ids,
                last_viewed_at__gte=cutoff_date,
                user__isnull=False,
            )
            .select_related("user")
            .order_by("insight_id", "-last_viewed_at")
        )

        viewers_by_insight: dict[int, list] = {}
        for viewer in all_viewers:
            iid = viewer.insight_id
            if iid not in viewers_by_insight:
                viewers_by_insight[iid] = []
            if len(viewers_by_insight[iid]) < 3:
                viewers_by_insight[iid].append(viewer.user)

        instance_map = {instance.pk: instance for instance in queryset}
        for item in data:
            item["viewers"] = UserBasicSerializer(viewers_by_insight.get(item["id"], []), many=True).data
            instance = instance_map.get(item["id"])
            item["view_count"] = getattr(instance, "view_count", 0) if instance else 0

        return Response(data=data, status=status.HTTP_200_OK)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                if str_to_bool(request.GET["saved"]):
                    visible_tile_for_insight = DashboardTile.objects.filter(insight=OuterRef("pk")).exclude(
                        dashboard__creation_mode="unlisted"
                    )
                    queryset = queryset.filter(Q(saved=True) | Exists(visible_tile_for_insight))
                else:
                    queryset = queryset.filter(Q(saved=False))
            elif key == "feature_flag":
                feature_flag = request.GET["feature_flag"]
                feature_flag_breakdown = f"$feature/{feature_flag}"
                # Legacy insights store breakdown in `filters.breakdown` and reference
                # the flag name in `filters.properties`. Query-based insights store
                # breakdown config in the `query` JSON field (e.g. inside
                # `breakdownFilter.breakdown`). The properties search uses the raw flag
                # name because legacy filters reference it without the `$feature/` prefix.
                queryset = queryset.filter(
                    Q(filters__breakdown__icontains=feature_flag_breakdown)
                    | Q(filters__properties__icontains=feature_flag)
                    | Q(query__icontains=feature_flag_breakdown)
                )
            elif key == "events":
                events_filter = request.GET["events"]
                events = json.loads(events_filter) if events_filter else []
                for event in events:
                    queryset = queryset.filter(Q(query_metadata__events__contains=[event]))
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "favorited":
                queryset = queryset.filter(Q(favorited=True))
            elif key == "hide_feature_flag_insights":
                if str_to_bool(request.GET["hide_feature_flag_insights"]):
                    # Exclude insights with the specific feature flag names
                    from posthog.helpers.dashboard_templates import (
                        FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
                        FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME,
                    )

                    queryset = queryset.exclude(
                        name__in=[FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME, FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME]
                    )
            elif key == "date_from":
                queryset = queryset.filter(
                    last_modified_at__gt=relative_date_parse(request.GET["date_from"], self.team.timezone_info)
                )
            elif key == "date_to":
                queryset = queryset.filter(
                    last_modified_at__lt=relative_date_parse(request.GET["date_to"], self.team.timezone_info)
                )
            elif key == INSIGHT:
                insight = request.GET[INSIGHT]
                legacy_filter = Q(query__isnull=True) & Q(filters__insight=insight)
                legacy_to_hogql_mapping = {
                    "TRENDS": schema.NodeKind.TRENDS_QUERY,
                    "FUNNELS": schema.NodeKind.FUNNELS_QUERY,
                    "RETENTION": schema.NodeKind.RETENTION_QUERY,
                    "PATHS": schema.NodeKind.PATHS_QUERY,
                    "STICKINESS": schema.NodeKind.STICKINESS_QUERY,
                    "LIFECYCLE": schema.NodeKind.LIFECYCLE_QUERY,
                }
                if insight == "JSON":
                    queryset = queryset.filter(query__isnull=False)
                    queryset = queryset.exclude(query__kind__in=WRAPPER_NODE_KINDS, query__source__kind="HogQLQuery")
                    queryset = queryset.exclude(
                        query__kind__in=WRAPPER_NODE_KINDS, query__source__kind__in=legacy_to_hogql_mapping.values()
                    )
                elif insight == "SQL":
                    queryset = queryset.filter(query__isnull=False)
                    queryset = queryset.filter(query__kind__in=WRAPPER_NODE_KINDS, query__source__kind="HogQLQuery")
                elif insight in legacy_to_hogql_mapping:
                    queryset = queryset.filter(
                        legacy_filter
                        | Q(query__isnull=False)
                        & Q(query__kind=schema.NodeKind.INSIGHT_VIZ_NODE)
                        & Q(query__source__kind=legacy_to_hogql_mapping[insight])
                    )
                else:
                    queryset = queryset.filter(legacy_filter)
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"])
                    | Q(derived_name__icontains=request.GET["search"])
                    | Q(tagged_items__tag__name__icontains=request.GET["search"])
                    | Q(description__icontains=request.GET["search"])
                )
            elif key == "dashboards":
                dashboards_filter = request.GET["dashboards"]
                if dashboards_filter:
                    dashboards_ids = json.loads(dashboards_filter)
                    for dashboard_id in dashboards_ids:
                        # filter by dashboards one at a time so the filter is AND not OR
                        queryset = queryset.filter(
                            id__in=DashboardTile.objects.filter(dashboard__id=dashboard_id)
                            .values_list("insight__id", flat=True)
                            .all()
                        )
            elif key == "tags":
                tags_filter = request.GET["tags"]
                if tags_filter:
                    tags_list = json.loads(tags_filter)
                    if tags_list:
                        queryset = queryset.filter(tagged_items__tag__name__in=tags_list).distinct()
            elif key == "created_by":
                created_by_filter = request.GET["created_by"]
                if created_by_filter:
                    created_by_ids = json.loads(created_by_filter)
                    if created_by_ids:
                        queryset = queryset.filter(created_by__id__in=created_by_ids)
            elif key == "created_date_from":
                queryset = queryset.filter(
                    created_at__gt=relative_date_parse(request.GET["created_date_from"], self.team.timezone_info)
                )
            elif key == "created_date_to":
                queryset = queryset.filter(
                    created_at__lt=relative_date_parse(request.GET["created_date_to"], self.team.timezone_info)
                )
            elif key == "last_viewed_date_from":
                queryset = queryset.filter(
                    last_viewed_at__gt=relative_date_parse(
                        request.GET["last_viewed_date_from"], self.team.timezone_info
                    )
                )
            elif key == "last_viewed_date_to":
                queryset = queryset.filter(
                    last_viewed_at__lt=relative_date_parse(request.GET["last_viewed_date_to"], self.team.timezone_info)
                )

        return queryset

    @extend_schema(
        parameters=[
            INSIGHT_ID_PATH_PARAMETER,
            OpenApiParameter(
                name="refresh",
                enum=[*ExecutionMode],
                default=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                # Sync the `refresh` description here with the other one in this file, and with frontend/src/queries/schema.ts
                description="""
Whether to refresh the insight, how aggresively, and if sync or async:
- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
- `'force_blocking'` - calculate synchronously, even if fresh results are already cached
- `'force_async'` - kick off background calculation, even if fresh results are already cached
Background calculation can be tracked using the `query_status` response field.""",
            ),
            OpenApiParameter(
                name="from_dashboard",
                type=OpenApiTypes.INT,
                description="""
Only if loading an insight in the context of a dashboard: The relevant dashboard's ID.
When set, the specified dashboard's filters and date range override will be applied.""",
            ),
        ],
    )
    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="GET")
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer_context = self.get_serializer_context()

        dashboard_tile: DashboardTile | None = None
        dashboard_id = request.query_params.get("from_dashboard", None)
        if dashboard_id is not None:
            dashboard_tile = (
                DashboardTile.objects.filter(dashboard__id=dashboard_id, insight__id=instance.id)
                .select_related("dashboard")
                .first()
            )

        if dashboard_tile is not None:
            # context is used in the to_representation method to report filters used
            serializer_context.update({"dashboard": dashboard_tile.dashboard})

        try:
            serialized_data = self.get_serializer(instance, context=serializer_context).data
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))

        if dashboard_tile is not None:
            serialized_data["color"] = dashboard_tile.color
            layouts = dashboard_tile.layouts
            # workaround because DashboardTiles layouts were migrated as stringified JSON :/
            if isinstance(layouts, str):
                layouts = json.loads(layouts)

            serialized_data["layouts"] = layouts

        response = Response(serialized_data)

        return response

    @action(methods=["GET"], detail=True)
    def analyze(self, request: Request, **kwargs) -> Response:
        self._validate_ai_feature_access()

        insight = self.get_object()

        if not insight.query:
            return Response({"result": ""})

        try:
            query = schema.InsightVizNode.model_validate(insight.query)
        except Exception:
            return Response({"result": ""})

        result = None
        try:
            # We try to get cached result.
            result_ctx = process_query_model(
                self.team,
                query,
                execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                user=request.user if request.user.is_authenticated else None,
                analytics_props=get_request_analytics_properties(request),
            )
            if isinstance(result_ctx, BaseModel):
                result = result_ctx.model_dump()
            else:
                result = result_ctx

            if result and result.get("results") is None and result.get("result") is None:
                result = None
        except Exception:
            result = None

        analysis = get_insight_analysis(
            query,
            self.team,
            result,
            insight_name=insight.name,
            insight_description=insight.description,
        )

        return Response({"result": analysis})

    @action(methods=["GET", "POST"], detail=True)
    def suggestions(self, request: Request, **kwargs) -> Response:
        self._validate_ai_feature_access()

        insight = self.get_object()

        if not insight.query:
            return Response([])

        try:
            query = schema.InsightVizNode.model_validate(insight.query)
        except Exception:
            return Response([])

        result = None
        try:
            # We try to get cached result.
            result_ctx = process_query_model(
                self.team,
                query,
                execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                user=request.user if request.user.is_authenticated else None,
                analytics_props=get_request_analytics_properties(request),
            )
            if isinstance(result_ctx, BaseModel):
                result = result_ctx.model_dump()
            else:
                result = result_ctx

            if result and result.get("results") is None and result.get("result") is None:
                result = None
        except Exception:
            result = None

        # Get context from POST body if provided
        context = None
        if request.method == "POST":
            context = request.data.get("context")

        suggestions = get_insight_suggestions(query, self.team, result, context)

        return Response([s.model_dump() for s in suggestions])

    @action(methods=["POST"], detail=False, required_scopes=["insight:write"])
    def generate_metadata(self, request: Request, **kwargs) -> Response:
        """Generate an AI-suggested name and description for an insight based on its query configuration."""
        self._validate_ai_feature_access()

        query_data = request.data.get("query")
        if not query_data:
            raise ValidationError("Missing 'query' field in request body")

        kind = query_data.get("kind")

        try:
            if kind == "ActorsQuery":
                validated_query: (
                    schema.InsightVizNode | schema.ActorsQuery | schema.EventsQuery | schema.GroupsQuery
                ) = schema.ActorsQuery.model_validate(query_data)
            elif kind == "EventsQuery":
                validated_query = schema.EventsQuery.model_validate(query_data)
            elif kind == "GroupsQuery":
                validated_query = schema.GroupsQuery.model_validate(query_data)
            else:
                validated_query = schema.InsightVizNode.model_validate(query_data)
        except Exception:
            raise ValidationError("Invalid query format")

        try:
            metadata = generate_insight_metadata(validated_query, self.team)
        except Exception as e:
            capture_exception(e)
            raise APIException("Failed to generate insight metadata. Please try again.")

        return Response({"name": metadata.name, "description": metadata.description})

    def _run_legacy_query(
        self,
        request: request.Request,
        filter_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Convert Filter-style params to a query and run via process_query_dict.

        Uses the unified QueryRunner cache instead of the legacy @cached_by_filters system.
        """
        team = self.team
        filter = Filter(request=request, team=team)
        if filter_overrides:
            filter = filter.shallow_clone(overrides=filter_overrides)

        query_dict = filter_to_query(filter.to_dict()).model_dump()

        refresh = refresh_requested_by_client(request)
        if refresh:
            execution_mode = execution_mode_from_refresh(refresh)
        else:
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

        # Legacy endpoints never supported async — restrict to blocking modes
        if execution_mode not in BLOCKING_EXECUTION_MODES:
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

        query_response = process_query_dict(
            team,
            query_dict,
            execution_mode=execution_mode,
            user=request.user if isinstance(request.user, User) else None,
            analytics_props=get_request_analytics_properties(request),
        )

        if isinstance(query_response, BaseModel):
            return {
                "result": getattr(query_response, "results", []),
                "timezone": getattr(query_response, "timezone", team.timezone),
                "is_cached": getattr(query_response, "is_cached", False),
                "last_refresh": getattr(query_response, "last_refresh", None),
            }
        return {
            "result": query_response.get("results", query_response.get("result", [])),
            "timezone": query_response.get("timezone", team.timezone),
            "is_cached": query_response.get("is_cached", False),
            "last_refresh": query_response.get("last_refresh", None),
        }

    @extend_schema(exclude=True)
    @action(methods=["GET", "POST"], detail=False, required_scopes=["insight:read"])
    def trend(self, request: request.Request, *args: Any, **kwargs: Any):
        capture_legacy_api_call(request, self.team)

        timings = HogQLTimings()
        try:
            with timings.measure("calculate"):
                result = self._run_legacy_query(request)
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except UserAccessControlError as e:
            raise ValidationError(str(e))
        except Cohort.DoesNotExist as e:
            raise ValidationError(str(e))

        filter = Filter(request=request, team=self.team)

        params_breakdown_limit = request.GET.get("breakdown_limit")
        if params_breakdown_limit is not None and params_breakdown_limit != "":
            breakdown_values_limit = int(params_breakdown_limit)
        else:
            breakdown_values_limit = BREAKDOWN_VALUES_LIMIT

        next = (
            format_paginated_url(request, filter.offset, breakdown_values_limit)
            if len(result["result"]) >= breakdown_values_limit
            else None
        )
        if self.request.accepted_renderer.format == "csv":
            csvexport = []
            for item in result["result"]:
                line = {"series": (item["action"].get("custom_name") if item["action"] else None) or item["label"]}
                for index, data in enumerate(item["data"]):
                    line[item["labels"][index]] = data
                csvexport.append(line)
            renderer = csvrenderers.CSVRenderer()
            renderer.header = csvexport[0].keys()
            export = renderer.render(csvexport)
            if request.GET.get("export_insight_id"):
                export = "{}/insights/{}/\n".format(SITE_URL, request.GET["export_insight_id"]).encode() + export

            response = HttpResponse(export)
            response["Content-Disposition"] = (
                'attachment; filename="{name} ({date_from} {date_to}) from PostHog.csv"'.format(
                    name=slugify(request.GET.get("export_name", "export")),
                    date_from=filter.date_from.strftime("%Y-%m-%d -") if filter.date_from else "up until",
                    date_to=filter.date_to.strftime("%Y-%m-%d"),
                )
            )
            return response

        result["timings"] = [val.model_dump() for val in timings.to_list()]

        return Response({**result, "next": next})

    @extend_schema(exclude=True)
    @action(methods=["GET", "POST"], detail=False, required_scopes=["insight:read"])
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        capture_legacy_api_call(request, self.team)

        timings = HogQLTimings()
        try:
            with timings.measure("calculate"):
                funnel = self._run_legacy_query(request, filter_overrides={"insight": "FUNNELS"})
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))

        if isinstance(funnel["result"], BaseModel):
            funnel["result"] = funnel["result"].model_dump()
        funnel["result"] = protect_old_clients_from_multi_property_default(request.data, funnel["result"])
        funnel["timings"] = [val.model_dump() for val in timings.to_list()]

        return Response(funnel)

    # ******************************************
    # /projects/:id/insights/viewed
    # Creates or updates InsightViewed objects for the user/insight combo(s)
    # Accepts an array of insight_ids
    # ******************************************
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def viewed(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        """
        Update insight view timestamps.
        Expects: {"insight_ids": [1, 2, 3, ...]}
        """
        insight_ids = request.data.get("insight_ids")

        if not insight_ids or not isinstance(insight_ids, list):
            raise serializers.ValidationError({"insight_ids": "Must be a non-empty list of insight IDs"})

        insights = Insight.objects.filter(
            id__in=insight_ids,
            team__project_id=self.team.project_id,
            deleted=False,
        )

        viewed_at = now()
        for insight in insights:
            InsightViewed.objects.update_or_create(
                team=self.team,
                user=request.user,
                insight=insight,
                defaults={"last_viewed_at": viewed_at},
            )

        return Response(status=status.HTTP_201_CREATED)

    @extend_schema(operation_id="insights_all_activity_retrieve")
    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Insight", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item = self.get_object()

        activity_page = load_activity(
            scope="Insight",
            team_id=self.team_id,
            item_ids=[str(item.id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["POST"], detail=False)
    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="CANCEL")
    def cancel(self, request: request.Request, **kwargs):
        if "client_query_id" not in request.data:
            raise serializers.ValidationError({"client_query_id": "Field is required."})
        cancel_query_on_cluster(team_id=self.team.pk, client_query_id=request.data["client_query_id"])
        return Response(status=status.HTTP_201_CREATED)

    @extend_schema(exclude=True)  # internal endpoint, not for public use
    @action(methods=["POST"], detail=False)
    def timing(self, request: request.Request, **kwargs):
        from posthog.kafka_client.routing import get_producer
        from posthog.models.event.util import format_clickhouse_timestamp
        from posthog.utils import cast_timestamp_or_now

        if CAPTURE_TIME_TO_SEE_DATA:
            payload = {
                **request.data,
                "team_id": self.team_id,
                "user_id": self.request.user.pk,
                "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
            }
            if "min_last_refresh" in payload:
                payload["min_last_refresh"] = format_clickhouse_timestamp(payload["min_last_refresh"])
            if "max_last_refresh" in payload:
                payload["max_last_refresh"] = format_clickhouse_timestamp(payload["max_last_refresh"])
            get_producer(topic=KAFKA_METRICS_TIME_TO_SEE_DATA).produce(
                topic=KAFKA_METRICS_TIME_TO_SEE_DATA, data=payload
            )

        return Response(status=status.HTTP_201_CREATED)


class LegacyInsightViewSet(InsightViewSet):
    param_derived_from_user_current_team = "project_id"
