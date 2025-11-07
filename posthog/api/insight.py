import json
import logging
from functools import lru_cache
from typing import Any, Optional, Union, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Max, Prefetch, QuerySet
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
from prometheus_client import Counter
from pydantic import BaseModel
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import ParseError, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import QueryStatus

from posthog.hogql.constants import BREAKDOWN_VALUES_LIMIT
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog import schema
from posthog.api.documentation import extend_schema, extend_schema_field, extend_schema_serializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight_variable import map_stale_to_latest
from posthog.api.monitoring import Feature, monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action, format_paginated_url
from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication
from posthog.caching.fetch_from_cache import InsightResult
from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import INSIGHT, INSIGHT_FUNNELS, INSIGHT_STICKINESS, TRENDS_STICKINESS, FunnelVizType
from posthog.decorators import cached_by_filters
from posthog.event_usage import groups
from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default
from posthog.hogql_queries.apply_dashboard_filters import (
    WRAPPER_NODE_KINDS,
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.hogql_queries.legacy_compatibility.feature_flag import get_query_method, hogql_insights_replace_filters
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.query_runner import (
    ExecutionMode,
    execution_mode_from_refresh,
    get_query_runner,
    shared_insights_execution_mode,
)
from posthog.kafka_client.topics import KAFKA_METRICS_TIME_TO_SEE_DATA
from posthog.models import Cohort, DashboardTile, Filter, Insight, User
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    changes_between,
    describe_change,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.alert import AlertConfiguration, are_alerts_supported_for_insight
from posthog.models.dashboard import Dashboard
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.models.insight import InsightViewed
from posthog.models.insight_variable import InsightVariable
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT
from posthog.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.trends import Trends
from posthog.queries.util import get_earliest_timestamp
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlError, UserAccessControlSerializerMixin
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

logger = structlog.get_logger(__name__)

INSIGHT_REFRESH_INITIATED_COUNTER = Counter(
    "insight_refresh_initiated",
    "Insight refreshes initiated, based on should_refresh_insight().",
    labelnames=["is_shared"],
)


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
    changes: Optional[list[Change]] = None,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Insight id and short_id are passed separately as some activities (like delete) alter the Insight instance

    The experiments feature creates insights without a name, this does not log those
    """
    insight_name: Optional[str] = insight.name if insight.name else insight.derived_name
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
        if properties is None:
            properties = {}
        organization = Organization.objects.get(id=organization_id)
        team = Team.objects.get(id=team_id)
        if not was_impersonated and user.distinct_id:
            posthoganalytics.capture(
                f"insight {activity}",
                distinct_id=user.distinct_id,
                properties={"insight_id": insight_short_id, **properties},
                groups=(groups(organization, team) if team_id else groups(organization)),
            )


def capture_legacy_api_call(request: request.Request, team: Team):
    try:
        event = "legacy insight endpoint called"
        distinct_id: str = request.user.distinct_id  # type: ignore
        properties = {
            "path": request._request.path,
            "method": request._request.method,
            "query_method": get_query_method(request=request, team=team),
            "filter": get_filter(request=request, team=team),
            "was_impersonated": is_impersonated_session(request),
        }

        posthoganalytics.capture(
            event, distinct_id=distinct_id, properties=properties, groups=(groups(team.organization, team))
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

    def get_last_viewed_at(self, instance: Insight):
        """Get the last viewed timestamp for this insight by any user in the team."""
        return getattr(instance, "last_viewed_at", None)

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        representation["dashboards"] = [tile["dashboard_id"] for tile in representation["dashboard_tiles"]]

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

    @lru_cache(maxsize=1)
    def _dashboard_tiles(self, instance):
        return [tile.dashboard_id for tile in instance.dashboard_tiles.all()]


@extend_schema_field(
    {
        "type": "object",
        "example": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [
                    {"kind": "EventsNode", "math": "total", "name": "$pageview", "event": "$pageview", "version": 1}
                ],
                "version": 1,
            },
            "version": 1,
        },
    }
)
class QueryFieldSerializer(serializers.Serializer):
    def to_representation(self, value):
        return self.parent._query_variables_mapping(value)  # type: ignore

    def to_internal_value(self, data):
        if data is not None and not isinstance(data, dict):
            raise serializers.ValidationError("Query must be a valid JSON object")
        return data


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
    dashboards = serializers.PrimaryKeyRelatedField(
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

    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="POST")
    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        tags = validated_data.pop("tags", None)  # tags are created separately as global tag relationships
        team_id = self.context["team_id"]
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

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
            for dashboard in Dashboard.objects.filter(id__in=[d.id for d in dashboards]).all():
                if dashboard.team != insight.team:
                    raise serializers.ValidationError("Dashboard not found")

                DashboardTile.objects.create(insight=insight, dashboard=dashboard, last_refresh=now())

        # Manual tag creation since this create method doesn't call super()
        self._attempt_set_tags(tags, insight)

        properties = {}
        properties["$current_url"] = current_url
        properties["$session_id"] = session_id

        log_and_report_insight_activity(
            activity="created",
            insight=insight,
            insight_id=insight.id,
            insight_short_id=insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team_id,
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            properties=properties,
        )

        return insight

    @transaction.atomic()
    @monitor(feature=Feature.INSIGHT, endpoint="insight", method="PATCH")
    def update(self, instance: Insight, validated_data: dict, **kwargs) -> Insight:
        current_url = self.context["request"].headers.get("Referer")
        session_id = self.context["request"].headers.get("X-Posthog-Session-Id")
        dashboards_before_change: list[Union[str, dict]] = []
        try:
            # since it is possible to be undeleting a soft deleted insight
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
        if not are_alerts_supported_for_insight(updated_insight):
            instance.alertconfiguration_set.all().delete()

        self._log_insight_update(before_update, dashboards_before_change, updated_insight, current_url, session_id)

        self.user_permissions.reset_insights_dashboard_cached_results()

        return updated_insight

    def _log_insight_update(
        self,
        before_update,
        dashboards_before_change,
        updated_insight,
        current_url,
        session_id,
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

        properties = {}
        properties["$current_url"] = current_url
        properties["$session_id"] = session_id

        log_and_report_insight_activity(
            activity="updated",
            insight=updated_insight,
            insight_id=updated_insight.id,
            insight_short_id=updated_insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            changes=changes,
            properties=properties,
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
        candidate_dashboards = Dashboard.objects.filter(id__in=ids_to_add)
        dashboard: Dashboard
        for dashboard in candidate_dashboards:
            # does this user have permission on dashboards to add... if they are restricted
            # it will mean this dashboard becomes restricted because of the patch
            if (
                self.user_permissions.dashboard(dashboard).effective_privilege_level
                == Dashboard.PrivilegeLevel.CAN_VIEW
            ):
                raise PermissionDenied(f"You don't have permission to add insights to dashboard: {dashboard.id}")

            if dashboard.team != instance.team:
                raise serializers.ValidationError("Dashboard not found")

            tile, _ = DashboardTile.objects_including_soft_deleted.get_or_create(insight=instance, dashboard=dashboard)

            if tile.deleted:
                tile.deleted = False
                tile.save()

        if ids_to_remove:
            DashboardTile.objects.filter(dashboard_id__in=ids_to_remove, insight=instance).update(deleted=True)

        self.context["after_dashboard_changes"] = [describe_change(d) for d in dashboards if not d.deleted]

    def get_result(self, insight: Insight):
        return self.insight_result(insight).result

    def get_hasMore(self, insight: Insight):
        return self.insight_result(insight).has_more

    def get_columns(self, insight: Insight):
        return self.insight_result(insight).columns

    def get_timezone(self, insight: Insight):
        # :TODO: This doesn't work properly as background cache updates don't set timezone in the response.
        # This should get refactored.
        if refresh_requested_by_client(self.context["request"]):
            return insight.team.timezone

        return self.insight_result(insight).timezone

    def get_last_refresh(self, insight: Insight):
        return self.insight_result(insight).last_refresh

    def get_cache_target_age(self, insight: Insight):
        return self.insight_result(insight).cache_target_age

    def get_next_allowed_client_refresh(self, insight: Insight):
        return self.insight_result(insight).next_allowed_client_refresh

    def get_is_cached(self, insight: Insight):
        return self.insight_result(insight).is_cached

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

    def get_hogql(self, insight: Insight):
        return self.insight_result(insight).hogql

    def get_types(self, insight: Insight):
        return self.insight_result(insight).types

    def get_alerts(self, insight: Insight):
        if not are_alerts_supported_for_insight(insight):
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
        else:
            representation["dashboards"] = [tile["dashboard_id"] for tile in representation["dashboard_tiles"]]

        dashboard: Optional[Dashboard] = self.context.get("dashboard")
        request: Optional[Request] = self.context.get("request")
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

    @lru_cache(maxsize=1)
    def insight_result(self, insight: Insight) -> InsightResult:
        from posthog.caching.calculate_results import calculate_for_query_based_insight

        dashboard: Optional[Dashboard] = self.context.get("dashboard")

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

                if self.context.get("is_shared", False):
                    execution_mode = shared_insights_execution_mode(execution_mode)

                return calculate_for_query_based_insight(
                    insight,
                    team=self.context["get_team"](),
                    dashboard=dashboard,
                    execution_mode=execution_mode,
                    user=None if self.context["request"].user.is_anonymous else self.context["request"].user,
                    filters_override=filters_override,
                    variables_override=variables_override,
                    tile_filters_override=tile_filters_override,
                )
            except ExposedHogQLError as e:
                raise ValidationError(str(e))
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

    @lru_cache(maxsize=1)  # each serializer instance should only deal with one insight/tile combo
    def dashboard_tile_from_context(self, insight: Insight, dashboard: Optional[Dashboard]) -> Optional[DashboardTile]:
        dashboard_tile: Optional[DashboardTile] = self.context.get("dashboard_tile", None)

        if dashboard_tile and dashboard_tile.deleted:
            self.context.update({"dashboard_tile": None})
            dashboard_tile = None

        if not dashboard_tile and dashboard:
            dashboard_tile = DashboardTile.dashboard_queryset(
                DashboardTile.objects.filter(insight=insight, dashboard=dashboard)
            ).first()

        return dashboard_tile


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="refresh",
                enum=list(ExecutionMode),
                default=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                # Sync the `refresh` description here with the other one in this file, and with frontend/src/queries/schema.ts
                description="""
Whether to refresh the retrieved insights, how aggresively, and if sync or async:
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
        ]
    ),
)
class InsightViewSet(
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
    renderer_classes = (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.CSVRenderer)
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    sharing_enabled_actions = ["retrieve", "list"]
    queryset = Insight.objects_including_soft_deleted.all()

    stickiness_query_class = Stickiness
    parser_classes = (QuerySchemaParser,)

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if (self.action == "list" or self.action == "retrieve") and str_to_bool(
            self.request.query_params.get("basic", "0")
        ):
            return InsightBasicSerializer
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
            # an insight can be un-deleted by patching {"deleted": False}
            include_deleted = True

        if not include_deleted:
            queryset = queryset.exclude(deleted=True)

        queryset = queryset.prefetch_related(
            Prefetch(
                # TODO deprecate this field entirely
                "dashboards",
                queryset=Dashboard.objects.all().select_related("team__organization"),
            ),
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

        queryset = queryset.select_related("created_by", "last_modified_by", "team")
        if self.action == "list":
            queryset = queryset.prefetch_related("tagged_items__tag")
            queryset = queryset.annotate(last_viewed_at=Max("insightviewed__last_viewed_at"))
            queryset = self._filter_request(self.request, queryset)

        return self.order_queryset(queryset)

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
            .only("insight")
        )

        recently_viewed = [rv.insight for rv in (insight_queryset.order_by("-last_viewed_at")[:5])]

        response = InsightBasicSerializer(recently_viewed, many=True)
        return Response(data=response.data, status=status.HTTP_200_OK)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                if str_to_bool(request.GET["saved"]):
                    queryset = queryset.annotate(dashboards_count=Count("dashboards"))
                    queryset = queryset.filter(Q(saved=True) | Q(dashboards_count__gte=1))
                else:
                    queryset = queryset.filter(Q(saved=False))
            elif key == "feature_flag":
                feature_flag = request.GET["feature_flag"]
                queryset = queryset.filter(
                    Q(filters__breakdown__icontains=f"$feature/{feature_flag}")
                    | Q(filters__properties__icontains=feature_flag)
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

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="refresh",
                enum=list(ExecutionMode),
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

        dashboard_tile: Optional[DashboardTile] = None
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

        serialized_data = self.get_serializer(instance, context=serializer_context).data

        if dashboard_tile is not None:
            serialized_data["color"] = dashboard_tile.color
            layouts = dashboard_tile.layouts
            # workaround because DashboardTiles layouts were migrated as stringified JSON :/
            if isinstance(layouts, str):
                layouts = json.loads(layouts)

            serialized_data["layouts"] = layouts

        response = Response(serialized_data)

        return response

    @extend_schema(exclude=True)
    @action(methods=["GET", "POST"], detail=False, required_scopes=["insight:read"])
    def trend(self, request: request.Request, *args: Any, **kwargs: Any):
        capture_legacy_api_call(request, self.team)

        timings = HogQLTimings()
        try:
            with timings.measure("calculate"):
                query_method = get_query_method(request=request, team=self.team)
                if query_method == "hogql":
                    result = self.calculate_trends_hogql(request)
                else:
                    result = self.calculate_trends(request)
        except ExposedHogQLError as e:
            raise ValidationError(str(e))
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

    @cached_by_filters
    def calculate_trends(self, request: request.Request) -> dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=self.team)

        if filter.insight == INSIGHT_STICKINESS or filter.shown_as == TRENDS_STICKINESS:
            stickiness_filter = StickinessFilter(
                request=request,
                team=team,
                get_earliest_timestamp=get_earliest_timestamp,
            )
            result = self.stickiness_query_class().run(stickiness_filter, team)
        else:
            trends_query = Trends()
            result = trends_query.run(filter, team, is_csv_export=bool(request.GET.get("is_csv_export", False)))

        return {"result": result, "timezone": team.timezone}

    @cached_by_filters
    def calculate_trends_hogql(self, request: request.Request) -> dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=team)
        query = filter_to_query(filter.to_dict()).model_dump()
        query = upgrade(query)  # should not be necessary, but just in case
        query_runner = get_query_runner(query, team, limit_context=None)

        # we use the legacy caching mechanism (@cached_by_filters decorator), no need to cache in the query runner
        result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert (
            isinstance(result, schema.CachedTrendsQueryResponse)
            or isinstance(result, schema.CachedStickinessQueryResponse)
            or isinstance(result, schema.CachedLifecycleQueryResponse)
        )

        return {"result": result.results, "timezone": team.timezone}

    @extend_schema(exclude=True)
    @action(methods=["GET", "POST"], detail=False, required_scopes=["insight:read"])
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        capture_legacy_api_call(request, self.team)

        timings = HogQLTimings()
        try:
            with timings.measure("calculate"):
                query_method = get_query_method(request=request, team=self.team)
                if query_method == "hogql":
                    funnel = self.calculate_funnel_hogql(request)
                else:
                    funnel = self.calculate_funnel(request)

        except ExposedHogQLError as e:
            raise ValidationError(str(e))

        if isinstance(funnel["result"], BaseModel):
            funnel["result"] = funnel["result"].model_dump()
        funnel["result"] = protect_old_clients_from_multi_property_default(request.data, funnel["result"])
        funnel["timings"] = [val.model_dump() for val in timings.to_list()]

        return Response(funnel)

    @cached_by_filters
    def calculate_funnel(self, request: request.Request) -> dict[str, Any]:
        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)

        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            return {
                "result": ClickhouseFunnelTrends(team=team, filter=filter).run(),
                "timezone": team.timezone,
            }
        elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
            return {
                "result": ClickhouseFunnelTimeToConvert(team=team, filter=filter).run(),
                "timezone": team.timezone,
            }
        else:
            funnel_order_class = get_funnel_order_class(filter)
            return {
                "result": funnel_order_class(team=team, filter=filter).run(),
                "timezone": team.timezone,
            }

    @cached_by_filters
    def calculate_funnel_hogql(self, request: request.Request) -> dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=team)
        filter = filter.shallow_clone(overrides={"insight": "FUNNELS"})
        query = filter_to_query(filter.to_dict()).model_dump()
        query = upgrade(query)  # should not be necessary, but just in case
        query_runner = get_query_runner(query, team, limit_context=None)

        # we use the legacy caching mechanism (@cached_by_filters decorator), no need to cache in the query runner
        result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(result, schema.CachedFunnelsQueryResponse)

        return {"result": result.results, "timezone": team.timezone}

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
        if settings.IS_CONNECTED_TO_PROD_PG_IN_DEBUG:
            return Response(status=status.HTTP_204_NO_CONTENT)  # In the prod PG in debug mode, we can't write to PG
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

        item_id = kwargs["pk"]
        if not Insight.objects.filter(id=item_id, team__project_id=self.team.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="Insight",
            team_id=self.team_id,
            item_ids=[str(item_id)],
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
        from posthog.kafka_client.client import KafkaProducer
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
            KafkaProducer().produce(topic=KAFKA_METRICS_TIME_TO_SEE_DATA, data=payload)

        return Response(status=status.HTTP_201_CREATED)


class LegacyInsightViewSet(InsightViewSet):
    param_derived_from_user_current_team = "project_id"
