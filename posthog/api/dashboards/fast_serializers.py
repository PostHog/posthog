"""
Fast serializers for dashboard tiles to replace slow DRF serializers.
These provide 1:1 compatibility with the original DRF serializers but with better performance.
"""

import orjson
from typing import Any, Optional
from django.utils.timezone import now
from rest_framework.request import Request

from posthog.models import Dashboard, DashboardTile, Insight, Text, User
from posthog.utils import filters_override_requested_by_client, variables_override_requested_by_client
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.hogql_queries.legacy_compatibility.feature_flag import hogql_insights_replace_filters
from posthog.schema_migrations.upgrade import upgrade
from posthog.caching.fetch_from_cache import InsightResult
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.hogql_queries.query_runner import execution_mode_from_refresh, shared_insights_execution_mode
from posthog.utils import refresh_requested_by_client
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.hogql.errors import ExposedHogQLError
from posthog.api.insight_variable import map_stale_to_latest


def serialize_user_basic(user: Optional[User]) -> Optional[dict[str, Any]]:
    if not user:
        return None

    hedgehog_config = None
    if user.hedgehog_config:
        hedgehog_config = {
            "use_as_profile": user.hedgehog_config.get("use_as_profile"),
            "color": user.hedgehog_config.get("color"),
            "accessories": user.hedgehog_config.get("accessories"),
        }

    return {
        "id": user.id,
        "uuid": str(user.uuid),
        "distinct_id": user.distinct_id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "is_email_verified": user.is_email_verified,
        "hedgehog_config": hedgehog_config,
        "role_at_organization": user.role_at_organization,
    }


def serialize_text(text: Text) -> dict[str, Any]:
    return {
        "id": text.id,
        "body": text.body,
        "created_by": serialize_user_basic(text.created_by),
        "last_modified_at": text.last_modified_at.isoformat() if text.last_modified_at else None,
        "last_modified_by": serialize_user_basic(text.last_modified_by),
        "team": text.team_id,
    }


class FastInsightSerializer:
    def __init__(self, context: dict[str, Any]):
        self.context = context
        self._insight_result_cache: Optional[InsightResult] = None

    def insight_result(self, insight: Insight) -> InsightResult:
        """Cached insight result calculation - matches original InsightSerializer logic"""
        if self._insight_result_cache is not None:
            return self._insight_result_cache

        dashboard: Optional[Dashboard] = self.context.get("dashboard")

        with upgrade_query(insight):
            try:
                refresh_requested = refresh_requested_by_client(self.context["request"])
                execution_mode = execution_mode_from_refresh(refresh_requested)
                filters_override = filters_override_requested_by_client(self.context["request"], dashboard)
                variables_override = variables_override_requested_by_client(
                    self.context["request"], dashboard, list(self.context["insight_variables"])
                )

                if self.context.get("is_shared", False):
                    execution_mode = shared_insights_execution_mode(execution_mode)

                self._insight_result_cache = calculate_for_query_based_insight(
                    insight,
                    team=self.context["get_team"](),
                    dashboard=dashboard,
                    execution_mode=execution_mode,
                    user=None if self.context["request"].user.is_anonymous else self.context["request"].user,
                    filters_override=filters_override,
                    variables_override=variables_override,
                )
                return self._insight_result_cache

            except ExposedHogQLError:
                # Handle error case similar to original
                self._insight_result_cache = InsightResult(
                    result=None,
                    cache_key="error",
                    timezone="UTC",
                    last_refresh=now(),
                    query_status=None,
                    is_cached=False,
                )
                return self._insight_result_cache

    def _get_user_access_level(self, obj) -> Optional[str]:
        """Replicate UserAccessControlSerializerMixin.get_user_access_level logic"""
        # Follow the same logic as UserAccessControlSerializerMixin.user_access_control property
        user_access_control = None
        if "user_access_control" in self.context:
            user_access_control = self.context["user_access_control"]
        elif hasattr(self.context.get("view", None), "user_access_control"):
            user_access_control = self.context["view"].user_access_control
        elif "request" in self.context:
            from posthog.rbac.user_access_control import UserAccessControl
            from django.contrib.auth.models import AnonymousUser
            from typing import cast

            user = cast(User | AnonymousUser, self.context["request"].user)
            if user.is_anonymous:
                return None
            user = cast(User, user)
            user_access_control = UserAccessControl(user, organization_id=str(user.current_organization_id))

        if not user_access_control:
            return None

        return user_access_control.get_user_access_level(obj)

    def _query_variables_mapping(self, query: dict) -> dict:
        """Apply query variable mapping - matches original logic"""
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

    def serialize(self, insight: Insight) -> dict[str, Any]:
        """Fast orjson replacement for InsightSerializer.to_representation"""

        # Get dashboard tiles representation
        dashboard_tiles = [
            {"id": tile.id, "dashboard_id": tile.dashboard_id, "deleted": tile.deleted}
            for tile in insight.dashboard_tiles.all()
        ]

        # Build dashboards list from tiles (matches original logic)
        if self.context.get("after_dashboard_changes"):
            dashboards = [described_dashboard["id"] for described_dashboard in self.context["after_dashboard_changes"]]
        else:
            dashboards = [tile["dashboard_id"] for tile in dashboard_tiles]

        # Get dashboard and request context
        dashboard: Optional[Dashboard] = self.context.get("dashboard")
        request: Optional[Request] = self.context.get("request")
        dashboard_filters_override = filters_override_requested_by_client(request, dashboard) if request else None
        dashboard_variables_override = variables_override_requested_by_client(
            request, dashboard, list(self.context["insight_variables"])
        )

        # Handle query and filters logic (matches original InsightSerializer)
        if hogql_insights_replace_filters(insight.team) and (
            insight.query is not None or insight.query_from_filters is not None
        ):
            query = insight.query or insight.query_from_filters
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
                    insight.team,
                )
                query = apply_dashboard_variables_to_dict(
                    query,
                    dashboard_variables_override or {},
                    insight.team,
                )
            filters = {}
        else:
            filters = insight.dashboard_filters(
                dashboard=dashboard, dashboard_filters_override=dashboard_filters_override
            )

            # For the second branch, we need to map the insight query variables to match
            # the dashboard_variables_override IDs before calling get_effective_query
            base_query = insight.query or insight.query_from_filters or {}
            if base_query:
                base_query = self._query_variables_mapping(base_query)

            # Store the mapped query temporarily for get_effective_query to use
            original_query = insight.query
            insight.query = base_query if base_query else original_query

            try:
                query = insight.get_effective_query(
                    dashboard=dashboard,
                    dashboard_filters_override=dashboard_filters_override,
                    dashboard_variables_override=dashboard_variables_override,
                )
            finally:
                # Restore original query
                insight.query = original_query
            # Check if we need to add default "insight": "TRENDS"
            # This matches original DRF serializer logic
            if "insight" not in filters:
                # For insights without explicit insight type, default to TRENDS
                if not insight.query or (insight.filters and "insight" not in insight.filters):
                    filters["insight"] = "TRENDS"

        # Upgrade query to latest version
        query = upgrade(query)

        # Get insight result for performance fields
        insight_result = self.insight_result(insight)

        # Get user permissions (matches UserPermissionsSerializerMixin logic)
        user_permissions = self.context.get("user_permissions")
        if not user_permissions and "view" in self.context:
            user_permissions = getattr(self.context["view"], "user_permissions", None)

        # Calculate effective permission levels (matches original DRF serializer methods)
        if self.context.get("is_shared"):
            effective_restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            effective_privilege_level = Dashboard.PrivilegeLevel.CAN_VIEW
        else:
            effective_restriction_level = (
                user_permissions.insight(insight).effective_restriction_level if user_permissions else 21
            )
            effective_privilege_level = (
                user_permissions.insight(insight).effective_privilege_level if user_permissions else 37
            )

        # Get tags
        tags = []
        if hasattr(insight, "prefetched_tags"):
            tags = [tag.tag.name for tag in insight.prefetched_tags]
        else:
            tags = list(insight.tagged_items.values_list("tag__name", flat=True))

        # Build the complete representation
        representation = {
            # Basic fields from InsightBasicSerializer.Meta.fields
            "id": insight.id,
            "short_id": insight.short_id,
            "name": insight.name,
            "derived_name": insight.derived_name,
            "filters": filters,
            "query": query,
            "dashboards": dashboards,
            "dashboard_tiles": dashboard_tiles,
            "description": insight.description,
            "last_refresh": insight_result.last_refresh.isoformat() if insight_result.last_refresh else None,
            "refreshing": insight.refreshing,
            "saved": insight.saved,
            "tags": tags,
            "updated_at": insight.updated_at.isoformat() if insight.updated_at else None,
            "created_by": serialize_user_basic(insight.created_by),
            "created_at": insight.created_at.isoformat() if insight.created_at else None,
            "last_modified_at": insight.last_modified_at.isoformat() if insight.last_modified_at else None,
            "favorited": insight.favorited,
            "user_access_level": self._get_user_access_level(insight),
            # Additional fields from InsightSerializer.Meta.fields
            "order": insight.order,
            "deleted": insight.deleted,
            "cache_target_age": insight_result.cache_target_age,
            "next_allowed_client_refresh": insight_result.next_allowed_client_refresh.isoformat()
            if insight_result.next_allowed_client_refresh
            else None,
            "result": insight_result.result,
            "hasMore": insight_result.has_more,
            "columns": insight_result.columns,
            "last_modified_by": serialize_user_basic(insight.last_modified_by),
            "is_sample": insight.is_sample,
            "effective_restriction_level": effective_restriction_level,
            "effective_privilege_level": effective_privilege_level,
            "timezone": insight_result.timezone,
            "is_cached": insight_result.is_cached,
            "query_status": insight_result.query_status,
            "hogql": insight_result.hogql,
            "types": insight_result.types,
            "filters_hash": insight_result.cache_key,
        }

        # Hide PII fields when hideExtraDetails from SharingConfiguration is enabled
        if self.context.get("hide_extra_details", False):
            representation.pop("created_by", None)
            representation.pop("last_modified_by", None)
            representation.pop("created_at", None)
            representation.pop("last_modified_at", None)

        return representation


def serialize_dashboard_tile(tile: DashboardTile, context: dict[str, Any]) -> dict[str, Any]:
    # Handle layouts parsing (matches original logic)
    layouts = tile.layouts
    if isinstance(layouts, str):
        layouts = orjson.loads(layouts)

    # Base tile data
    representation = {
        "id": tile.id,
        "layouts": layouts,
        "color": tile.color,
        "insight": None,
        "text": None,
    }

    # Add order from context (matches original DashboardTileSerializer.to_representation)
    representation["order"] = context.get("order", None)

    # Serialize insight or text
    if tile.insight:
        fast_serializer = FastInsightSerializer(context)
        insight_data = fast_serializer.serialize(tile.insight)
        representation["insight"] = insight_data

        # Add last_refresh and is_cached from insight (matches original logic)
        representation["last_refresh"] = insight_data.get("last_refresh", None)
        representation["is_cached"] = insight_data.get("is_cached", False)
    elif tile.text:
        representation["text"] = serialize_text(tile.text)
        representation["last_refresh"] = None
        representation["is_cached"] = False

    return representation


def fast_serialize_tile_with_context(tile: DashboardTile, order: int, context: dict) -> tuple[int, dict]:
    """
    Returns (order, tile_data) tuple matching the original function signature.
    """
    # Create a copy of context to avoid thread conflicts (matches original)
    tile_context = context.copy()
    tile_context.update(
        {
            "dashboard_tile": tile,
            "order": order,
        }
    )

    try:
        tile_data = serialize_dashboard_tile(tile, tile_context)
        return order, tile_data
    except Exception as e:
        # Handle validation errors similar to original
        if not tile.insight:
            raise

        # Fallback handling for query validation errors
        query = tile.insight.query
        tile.insight.query = None
        tile_data = serialize_dashboard_tile(tile, tile_context)
        tile_data["insight"]["query"] = query
        tile_data["error"] = {"type": type(e).__name__, "message": str(e)}
        return order, tile_data
