from __future__ import annotations

import re
import json
import uuid
import builtins
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from enum import StrEnum
from typing import Any, Optional, TypedDict, cast

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    Exists,
    F,
    FilteredRelation,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Cast
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now

import structlog
import pydantic_core
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from opentelemetry import trace
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.schema import InsightVizNode

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.monitoring import Feature, monitor
from posthog.api.openapi_parameters import make_filters_override_param, make_variables_override_param
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import SearchMatchTypeSerializerMixin, UserBasicSerializer
from posthog.api.streaming import sse_streaming_response
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.client.async_task_chain import task_chain_context
from posthog.constants import GENERATED_DASHBOARD_PREFIX
from posthog.event_usage import EventSource, get_event_source, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers import create_dashboard_from_template
from posthog.helpers.dashboard_templates import create_from_template, dashboard_template_from_creation_payload
from posthog.helpers.trigram_search import (
    DESCRIPTION_FIELD,
    MAX_SEARCH_LENGTH,
    NAME_FIELD,
    apply_trigram_search,
    drop_similar_when_exact_exists,
)
from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system import FileSystem, create_or_update_file, delete_file, join_path, split_path
from posthog.models.quick_filter import QuickFilter
from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlSerializerMixin
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.resource_limits import LimitKey, check_count_limit
from posthog.session_recordings.session_recording_api import get_replay_listing_throttle_error
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.sync import database_sync_to_async
from posthog.user_permissions import UserPermissionsSerializerMixin
from posthog.utils import filters_override_requested_by_client, str_to_bool, variables_override_requested_by_client

from products.ai_observability.backend.dashboard_templates import get_ai_observability_default_template
from products.alerts.backend.models.alert import AlertConfiguration
from products.dashboards.backend.api.dashboard_template_json_schema_parser import (
    DashboardTemplateCreationJSONSchemaParser,
)
from products.dashboards.backend.api.widget_openapi_serializers import (
    WIDGET_BATCH_ADD_OPENAPI_HELP,
    AddDashboardWidgetRequestOpenApi,
    DashboardWidgetConfigField,
    PatchedDashboardOpenApiSerializer,
    UpdateDashboardWidgetRequestOpenApi,
    WidgetCatalogResponseSerializer,
)
from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT, MAX_WIDGETS_BATCH_SIZE
from products.dashboards.backend.feature_flags import dashboard_widgets_enabled
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import ButtonTile, DashboardTile, Text
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import (
    check_widget_tile_product_access,
    get_widget_api_scope_error,
    get_widget_product_access_error,
)
from products.dashboards.backend.widget_availability import get_widget_feature_enabled
from products.dashboards.backend.widget_catalog import get_widget_catalog_entries
from products.dashboards.backend.widget_create import prepare_widget_tile_create
from products.dashboards.backend.widget_layouts import (
    collect_dashboard_sm_layouts_for_dashboard,
    stack_widget_layout_at_bottom,
)
from products.dashboards.backend.widget_query_throttle import get_dashboard_widget_query_throttle_error
from products.dashboards.backend.widget_registry import (
    EXPECTED_WIDGET_TYPES,
    SESSION_REPLAY_LIST_WIDGET_TYPE,
    count_active_widget_filters,
    extract_widget_filters,
    get_widget_registry_entry,
    validate_widget_config,
)
from products.mcp_analytics.backend.dashboard_templates import get_mcp_analytics_default_template
from products.product_analytics.backend.api.insight import (
    DashboardTileBasicSerializer,
    InsightSerializer,
    InsightViewSet,
    _get_insight_type,
)
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable

from ee.hogai.utils.aio import async_to_sync

logger = structlog.get_logger(__name__)

DASHBOARD_SHARED_FIELDS = [
    "id",
    "name",
    "description",
    "pinned",
    "created_at",
    "created_by",
    "last_accessed_at",
    "last_viewed_at",
    "folder",
    "is_shared",
    "deleted",
    "creation_mode",
    "filters",
    "variables",
    "breakdown_colors",
    "data_color_theme_id",
    "tags",
    "restriction_level",
    "effective_restriction_level",
    "effective_privilege_level",
    "user_access_level",
    "access_control_version",
    "last_refresh",
    "persisted_filters",
    "persisted_variables",
    "team_id",
    "quick_filter_ids",
]


VARIABLES_OVERRIDE_PARAM = make_variables_override_param(subject_label="dashboard", tool_name="dashboard-get")
FILTERS_OVERRIDE_PARAM = make_filters_override_param(subject_label="dashboard")


tracer = trace.get_tracer(__name__)

RUN_WIDGETS_QUERY_CONCURRENCY = 4

WIDGET_TYPE_API_HELP = (
    "Widget type identifier. Supported values: "
    + ", ".join(sorted(EXPECTED_WIDGET_TYPES))
    + ". Use dashboard-widget-catalog-list for per-type config_schema documentation."
)


class _RunWidgetQueryWorkItem(TypedDict):
    tile_id: int
    widget_type: str
    query_fn: Any
    config: dict[str, Any]
    user: User | None


def _run_widget_query(
    team: Team,
    work_item: _RunWidgetQueryWorkItem,
    *,
    dashboard_id: int,
    distinct_id: str,
) -> dict[str, Any]:
    tile_id = work_item["tile_id"]
    widget_type = work_item["widget_type"]

    with slo_operation(
        spec=SloSpec(
            distinct_id=distinct_id,
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.DASHBOARD_WIDGET_DELIVERY,
            team_id=team.id,
            resource_id=str(tile_id),
        ),
        properties={
            "widget_type": widget_type,
            "dashboard_id": dashboard_id,
            "tile_id": tile_id,
        },
    ) as slo:
        try:
            query_fn = work_item["query_fn"]
            result = query_fn(
                team,
                work_item["config"],
                user=work_item["user"],
                include_total_count=False,
            )
            return {
                "tile_id": tile_id,
                "widget_type": widget_type,
                "result": result,
                "error": None,
            }
        except Exception:
            logger.exception("dashboard_run_widgets_failed", tile_id=tile_id, widget_type=widget_type)
            slo.fail()
            return {
                "tile_id": tile_id,
                "widget_type": widget_type,
                "result": None,
                "error": "Widget query failed. Please try again later.",
            }


def _tile_rects_overlap(rect_a: dict[str, int], rect_b: dict[str, int]) -> bool:
    return not (
        rect_a["x"] + rect_a["w"] <= rect_b["x"]
        or rect_b["x"] + rect_b["w"] <= rect_a["x"]
        or rect_a["y"] + rect_a["h"] <= rect_b["y"]
        or rect_b["y"] + rect_b["h"] <= rect_a["y"]
    )


def _compact_tile_layouts(tiles: list[DashboardTile]) -> set[int]:
    """Vertically compact tile layouts in place, mirroring the dashboard grid's default
    react-grid-layout vertical compaction (gravity up). Each breakpoint is compacted
    independently: tiles keep their x/w/h and are pulled up to the lowest free row.
    Returns the ids of tiles whose layouts changed.
    """
    for tile in tiles:
        if isinstance(tile.layouts, str):
            tile.layouts = json.loads(tile.layouts)

    changed: set[int] = set()
    breakpoints: set[str] = set()
    for tile in tiles:
        if isinstance(tile.layouts, dict):
            breakpoints.update(tile.layouts.keys())

    for breakpoint in breakpoints:
        entries = [
            tile for tile in tiles if isinstance(tile.layouts, dict) and isinstance(tile.layouts.get(breakpoint), dict)
        ]
        placed: list[dict[str, int]] = []
        for tile in DashboardTile.sort_tiles_by_layout(entries, breakpoint):
            layout = tile.layouts[breakpoint]
            rect = {"x": layout.get("x", 0), "y": layout.get("y", 0), "w": layout.get("w", 1), "h": layout.get("h", 1)}
            # Drop the tile to the lowest free row. Jump past colliding tiles rather than
            # scanning row-by-row, so an editor-supplied giant height can't blow up the loop.
            new_y = 0
            while True:
                collisions = [pr for pr in placed if _tile_rects_overlap({**rect, "y": new_y}, pr)]
                if not collisions:
                    break
                new_y = max(pr["y"] + pr["h"] for pr in collisions)
            placed.append({**rect, "y": new_y})
            if new_y != layout.get("y", 0):
                layout["y"] = new_y
                changed.add(tile.id)

    return changed


def serialize_tile_with_context(tile, order: int, context: dict) -> tuple[int, dict]:
    """
    Serialize a single tile with error handling. Returns (order, tile_data) tuple.
    This function is designed to be thread-safe and used with ThreadPoolExecutor.
    """
    # Create a copy of context to avoid thread conflicts
    tile_context = context.copy()
    tile_context.update(
        {
            "dashboard_tile": tile,
            "order": order,
        }
    )

    if isinstance(tile.layouts, str):
        tile.layouts = json.loads(tile.layouts)

    try:
        tile_data = DashboardTileSerializer(tile, many=False, context=tile_context).data
        return order, tile_data
    except pydantic_core.ValidationError as e:
        if not tile.insight:
            raise
        query = tile.insight.query
        tile.insight.query = None
        tile_data = DashboardTileSerializer(tile, context=tile_context).data
        tile_data["insight"]["query"] = query
        tile_data["error"] = {"type": type(e).__name__, "message": str(e)}
        return order, tile_data


class ReorderLayout(StrEnum):
    PRESERVE = "preserve"
    TWO_COLUMN = "two_column"
    FULL_WIDTH = "full_width"


DEFAULT_REORDER_TILE_WIDTH = 6
DEFAULT_REORDER_TILE_HEIGHT = 5


def _existing_sm_size(tile: DashboardTile, default_w: int, default_h: int) -> tuple[int, int]:
    sm = (tile.layouts or {}).get("sm") if isinstance(tile.layouts, dict) else None
    if not isinstance(sm, dict):
        return default_w, default_h
    w, h = sm.get("w"), sm.get("h")
    return (
        w if isinstance(w, int) and w > 0 else default_w,
        h if isinstance(h, int) and h > 0 else default_h,
    )


def _apply_reorder_layout(
    tile_order: list[int],
    tile_map: dict[int, DashboardTile],
    layout_mode: ReorderLayout,
) -> None:
    """Repack tiles. ``preserve`` keeps each tile's existing w/h and reuses the lowest-segment
    greedy algorithm from ``frontend/src/scenes/dashboard/tileLayouts.ts``; the other modes overwrite w/h."""
    if layout_mode == ReorderLayout.TWO_COLUMN:
        for index, tile_id in enumerate(tile_order):
            row, col = divmod(index, 2)
            tile_map[tile_id].layouts = {
                "sm": {
                    "x": col * DEFAULT_REORDER_TILE_WIDTH,
                    "y": row * DEFAULT_REORDER_TILE_HEIGHT,
                    "w": DEFAULT_REORDER_TILE_WIDTH,
                    "h": DEFAULT_REORDER_TILE_HEIGHT,
                },
                "xs": {"x": 0, "y": index * DEFAULT_REORDER_TILE_HEIGHT, "w": 1, "h": DEFAULT_REORDER_TILE_HEIGHT},
            }
        return

    if layout_mode == ReorderLayout.FULL_WIDTH:
        for index, tile_id in enumerate(tile_order):
            y = index * DEFAULT_REORDER_TILE_HEIGHT
            tile_map[tile_id].layouts = {
                "sm": {"x": 0, "y": y, "w": DASHBOARD_GRID_COLUMN_COUNT, "h": DEFAULT_REORDER_TILE_HEIGHT},
                "xs": {"x": 0, "y": y, "w": 1, "h": DEFAULT_REORDER_TILE_HEIGHT},
            }
        return

    column_heights = [0] * DASHBOARD_GRID_COLUMN_COUNT
    xs_y = 0
    for tile_id in tile_order:
        tile = tile_map[tile_id]
        existing_w, existing_h = _existing_sm_size(tile, DEFAULT_REORDER_TILE_WIDTH, DEFAULT_REORDER_TILE_HEIGHT)
        w = max(1, min(existing_w, DASHBOARD_GRID_COLUMN_COUNT))
        h = max(1, existing_h)

        # x=0 is the baseline candidate; scan the remaining start positions for a lower segment top,
        # keeping the leftmost on ties (the loop only updates on a strictly lower top).
        best_x = 0
        best_y = max(column_heights[0:w])
        for x in range(1, DASHBOARD_GRID_COLUMN_COUNT - w + 1):
            segment_top = max(column_heights[x : x + w])
            if segment_top < best_y:
                best_x = x
                best_y = segment_top

        tile.layouts = {
            "sm": {"x": best_x, "y": best_y, "w": w, "h": h},
            "xs": {"x": 0, "y": xs_y, "w": 1, "h": h},
        }
        for k in range(best_x, best_x + w):
            column_heights[k] = best_y + h
        xs_y += h


class ReorderTilesRequestSerializer(serializers.Serializer):
    tile_order = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="Array of tile IDs in the desired display order (top to bottom, left to right).",
    )
    layout = serializers.ChoiceField(
        choices=[mode.value for mode in ReorderLayout],
        default=ReorderLayout.PRESERVE.value,
        required=False,
        help_text=(
            "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height "
            "and only repacks positions in the new order. 'two_column' forces a 6-wide × 5-tall grid (two tiles per "
            "row). 'full_width' forces each tile to span the full 12-column row at height 5."
        ),
    )


class CopyDashboardTileRequestSerializer(serializers.Serializer):
    fromDashboardId = serializers.IntegerField(help_text="Dashboard id the tile currently belongs to.")
    tileId = serializers.IntegerField(help_text="Dashboard tile id to copy.")


class TileLayoutBoxSerializer(serializers.Serializer):
    x = serializers.IntegerField(required=False, help_text="Column position in the dashboard grid (0-indexed).")
    y = serializers.IntegerField(required=False, help_text="Row position in the dashboard grid (0-indexed).")
    w = serializers.IntegerField(
        required=False, help_text="Width in grid columns. The desktop grid is 12 columns wide."
    )
    h = serializers.IntegerField(required=False, help_text="Height in grid rows.")


class TileLayoutsSerializer(serializers.Serializer):
    sm = TileLayoutBoxSerializer(
        required=False,
        help_text="Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.",
    )
    xs = TileLayoutBoxSerializer(
        required=False,
        help_text="Layout for the small (mobile) breakpoint. The grid is 1 column wide.",
    )


class CreateTextTileRequestSerializer(serializers.Serializer):
    body = serializers.CharField(
        min_length=1,
        max_length=4000,
        required=True,
        allow_blank=False,
        help_text=(
            "Markdown body for the text tile. Supports headings, lists, and inline formatting. "
            "Useful as a dashboard section heading, divider, or annotation between insights. Max 4000 characters."
        ),
        error_messages={
            "min_length": "Text body cannot be empty",
            "max_length": "Text body cannot exceed 4000 characters",
        },
    )
    layouts = TileLayoutsSerializer(
        required=False,
        help_text=(
            "Optional grid layout per breakpoint. If omitted, the tile is placed at the bottom of the dashboard "
            "using the default size. Text tiles typically use a thin full-width banner (e.g. w=12, h=1)."
        ),
    )
    color = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional accent color name (e.g. 'blue', 'green', 'purple', 'black').",
        error_messages={"max_length": "Color cannot exceed 400 characters"},
    )


class UpdateTextTileRequestSerializer(serializers.Serializer):
    tile_id = serializers.IntegerField(
        required=True,
        help_text="ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.",
    )
    body = serializers.CharField(
        min_length=1,
        max_length=4000,
        required=False,
        allow_null=False,
        allow_blank=False,
        help_text="New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.",
        error_messages={
            "min_length": "Text body cannot be empty",
            "max_length": "Text body cannot exceed 4000 characters",
        },
    )
    layouts = TileLayoutsSerializer(
        required=False,
        help_text="New grid layout per breakpoint. Omit to leave the layout unchanged.",
    )
    color = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="New accent color name, empty string or null to clear. Omit to leave unchanged.",
        error_messages={"max_length": "Color cannot exceed 400 characters"},
    )


class DeleteTileRequestSerializer(serializers.Serializer):
    tile_id = serializers.IntegerField(
        required=True,
        help_text="ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs.",
    )


class MoveTileTileSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=True, help_text="Dashboard tile ID to move.")


class MoveTileRequestSerializer(serializers.Serializer):
    to_dashboard = serializers.IntegerField(required=True, help_text="Destination dashboard ID.")
    tile = MoveTileTileSerializer(required=True, help_text="Tile to move, identified by its dashboard tile ID.")


class DashboardWidgetCoreRequestSerializer(serializers.Serializer):
    widget_type = serializers.ChoiceField(
        choices=sorted(EXPECTED_WIDGET_TYPES),
        help_text=WIDGET_TYPE_API_HELP,
    )
    config = DashboardWidgetConfigField(
        required=False,
        help_text=(
            "Widget-specific configuration. Shape depends on widget_type; "
            "see dashboard-widget-catalog-list for per-type config_schema documentation. "
            f"Supported types: {', '.join(sorted(EXPECTED_WIDGET_TYPES))}."
        ),
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional custom display name for the widget tile.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional markdown description shown when show_description is enabled.",
    )


class AddDashboardWidgetRequestSerializer(DashboardWidgetCoreRequestSerializer):
    config = DashboardWidgetConfigField(
        help_text=(
            "Widget-specific configuration. Shape depends on widget_type; "
            "see dashboard-widget-catalog-list for per-type config_schema documentation. "
            f"Supported types: {', '.join(sorted(EXPECTED_WIDGET_TYPES))}."
        ),
    )
    layouts = TileLayoutsSerializer(
        required=False,
        help_text="Optional react-grid-layout positions keyed by breakpoint (sm, xs).",
    )
    show_description = serializers.BooleanField(
        required=False,
        help_text="Whether to show the description on the dashboard tile.",
    )


class DashboardPatchWidgetSerializer(DashboardWidgetCoreRequestSerializer):
    widget_type = serializers.ChoiceField(
        choices=sorted(EXPECTED_WIDGET_TYPES),
        required=False,
        help_text=WIDGET_TYPE_API_HELP,
    )
    id = serializers.UUIDField(
        required=False,
        help_text="Existing widget row ID when updating a widget tile via dashboard PATCH.",
    )


class AddDashboardWidgetsBatchRequestSerializer(serializers.Serializer):
    widgets = serializers.ListField(
        child=AddDashboardWidgetRequestSerializer(),
        min_length=1,
        max_length=MAX_WIDGETS_BATCH_SIZE,
        help_text=(
            f"Widget tiles to add atomically (1–{MAX_WIDGETS_BATCH_SIZE}). Use a single-element list to add one widget."
        ),
    )


class AddDashboardWidgetsBatchRequestOpenApiSerializer(serializers.Serializer):
    """OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents."""

    widgets = serializers.ListField(
        child=AddDashboardWidgetRequestOpenApi,
        min_length=1,
        max_length=MAX_WIDGETS_BATCH_SIZE,
        help_text=f"{WIDGET_BATCH_ADD_OPENAPI_HELP} (1–{MAX_WIDGETS_BATCH_SIZE} per request).",
    )


class UpdateWidgetRequestSerializer(serializers.Serializer):
    tile_id = serializers.IntegerField(
        required=True,
        help_text="ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.",
    )
    widget_type = serializers.ChoiceField(
        choices=sorted(EXPECTED_WIDGET_TYPES),
        required=False,
        help_text=f"{WIDGET_TYPE_API_HELP} Immutable; provide only to pick the config shape.",
    )
    config = DashboardWidgetConfigField(
        required=False,
        help_text=(
            "New widget configuration. Shape depends on the tile's widget_type; see "
            "dashboard-widget-catalog-list for per-type config_schema. Omit to leave unchanged."
        ),
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="New display name for the widget tile. Empty string or null clears it; omit to leave unchanged.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="New markdown description for the widget. Omit to leave unchanged.",
    )


class UpdateDashboardWidgetsBatchRequestSerializer(serializers.Serializer):
    widgets = serializers.ListField(
        child=UpdateWidgetRequestSerializer(),
        min_length=1,
        max_length=MAX_WIDGETS_BATCH_SIZE,
        help_text=(
            f"Widget tiles to update atomically (1–{MAX_WIDGETS_BATCH_SIZE}), each identified by its tile_id. "
            "Use a single-element list to update one widget."
        ),
    )


class UpdateDashboardWidgetsBatchRequestOpenApiSerializer(serializers.Serializer):
    """OpenAPI-only batch-update schema with widget_type-discriminated config shapes for agents."""

    widgets = serializers.ListField(
        child=UpdateDashboardWidgetRequestOpenApi,
        min_length=1,
        max_length=MAX_WIDGETS_BATCH_SIZE,
        help_text=(
            "Widget tiles to update atomically, each identified by its tile_id. config shape is per widget_type; "
            f"see dashboard-widget-catalog-list for per-type config_schema (1–{MAX_WIDGETS_BATCH_SIZE} per request)."
        ),
    )


class CanEditDashboard(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_object_permission(self, request: Request, view, dashboard) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return view.user_permissions.dashboard(dashboard).can_edit


class TextSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    body = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages={"max_length": "Text body cannot exceed 4000 characters"},
    )
    dashboard_tiles = DashboardTileBasicSerializer(many=True, read_only=True)

    class Meta:
        model = Text
        fields = "__all__"
        read_only_fields = ["id", "created_by", "last_modified_by", "last_modified_at"]


class ButtonTileSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    url = serializers.CharField(
        max_length=2000,
        error_messages={"max_length": "Button URL cannot exceed 2000 characters"},
    )
    text = serializers.CharField(
        max_length=200,
        error_messages={"max_length": "Button text cannot exceed 200 characters"},
    )
    placement = serializers.ChoiceField(choices=["left", "right"], default="left")
    dashboard_tiles = DashboardTileBasicSerializer(many=True, read_only=True)

    class Meta:
        model = ButtonTile
        fields = "__all__"
        read_only_fields = ["id", "created_by", "last_modified_by", "last_modified_at"]

    def validate_url(self, value: str) -> str:
        if value.startswith("/"):
            if not re.match(r"^/[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]*$", value):
                raise serializers.ValidationError("Pathname must start with / and contain valid URL path characters")
        else:
            validator = URLValidator(schemes=["http", "https"])
            try:
                validator(value)
            except Exception:
                raise serializers.ValidationError("Must be a valid URL or a pathname starting with /")
        return value


class DashboardWidgetSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    widget_type = serializers.CharField(
        max_length=64,
        help_text="Widget type identifier from the dashboard widget catalog.",
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional custom display name for this widget tile. Falls back to the widget catalog label when unset.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional markdown description shown on the dashboard tile when enabled.",
    )
    config = DashboardWidgetConfigField(
        required=False,
        help_text="Widget-specific configuration JSON for this widget type.",
    )
    dashboard_tiles = DashboardTileBasicSerializer(many=True, read_only=True)

    class Meta:
        model = DashboardWidget
        fields = "__all__"
        read_only_fields = ["id", "created_by", "last_modified_by", "last_modified_at"]


class SharedDashboardWidgetMetadataSerializer(serializers.ModelSerializer):
    """Tile header metadata for shared dashboards — no user fields or live query results."""

    widget_type = serializers.CharField(
        max_length=64,
        help_text="Widget type identifier from the dashboard widget catalog.",
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional custom display name for this widget tile. Falls back to the widget catalog label when unset.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional markdown description shown on the dashboard tile when enabled.",
    )
    config = DashboardWidgetConfigField(
        required=False,
        help_text="Widget-specific configuration JSON for this widget type.",
    )

    class Meta:
        model = DashboardWidget
        fields = ["id", "widget_type", "name", "description", "config"]
        read_only_fields = ["id", "widget_type", "name", "description", "config"]


class DashboardTileSerializer(serializers.ModelSerializer):
    id: serializers.IntegerField = serializers.IntegerField(required=False)
    insight = InsightSerializer()
    text = TextSerializer()
    button_tile = ButtonTileSerializer()
    widget = DashboardWidgetSerializer(required=False, allow_null=True)

    class Meta:
        model = DashboardTile
        exclude = [
            "dashboard",
            "deleted",
            "filters_hash",
            "last_refresh",
            "refreshing",
            "refresh_attempt",
            # Denormalization for HogQL printing; combined with depth=1, leaving it
            # in expands `team` into a full nested Team dict on every tile response.
            "team",
        ]
        read_only_fields = ["id", "insight"]
        depth = 1

    @tracer.start_as_current_span("DashboardTileSerializer.to_representation")
    def to_representation(self, instance: DashboardTile):
        representation = super().to_representation(instance)

        if self.context.get("is_shared") and instance.widget_id is not None:
            representation["widget"] = SharedDashboardWidgetMetadataSerializer(
                instance.widget, context=self.context
            ).data

        representation["order"] = self.context.get("order", None)

        insight_representation = representation["insight"] or {}  # May be missing for text tiles
        representation["last_refresh"] = insight_representation.get("last_refresh", None)
        representation["is_cached"] = insight_representation.get("is_cached", False)

        return representation


class InsightResultSerializer(InsightSerializer):
    """InsightSerializer restricted to identifiers + result only."""

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "derived_name",
            "result",
        ]
        read_only_fields = fields

    def to_representation(self, instance: Insight):
        # Skip InsightSerializer.to_representation which references fields
        # (dashboard_tiles, dashboards, etc.) we've excluded from this narrow serializer.
        return serializers.ModelSerializer.to_representation(self, instance)


class DashboardTileResultSerializer(DashboardTileSerializer):
    """DashboardTileSerializer restricted to tile id + insight result fields."""

    insight = InsightResultSerializer()

    class Meta:
        model = DashboardTile
        fields = ["id", "insight"]
        read_only_fields = ["id", "insight"]


class RunInsightsResponseSerializer(serializers.Serializer):
    results = DashboardTileResultSerializer(
        many=True,
        help_text="Results for each insight tile on the dashboard.",
    )


class DashboardWidgetRunResultSerializer(serializers.Serializer):
    tile_id = serializers.IntegerField(help_text="Dashboard tile ID for this widget result.")
    widget_type = serializers.CharField(
        allow_null=True,
        help_text="Widget type identifier, or null when the tile was not found.",
    )
    result = serializers.JSONField(
        allow_null=True,
        help_text=(
            "Live widget query result payload. List widgets return results (array), limit (configured page size), "
            "hasMore (boolean), totalCount (matching rows for current filters), totalCountCapped (true when totalCount "
            "hit the widget max and more may exist), and optional offset/nextOffset. error_tracking_list results are "
            "issue summaries; session_replay_list results are recording metadata."
        ),
    )
    error = serializers.CharField(
        allow_null=True,
        help_text="Error message when the widget could not be run.",
    )


class RunWidgetsResponseSerializer(serializers.Serializer):
    results = DashboardWidgetRunResultSerializer(
        many=True,
        help_text="Per-tile widget run results.",
    )


class AddDashboardWidgetsBatchResponseSerializer(serializers.Serializer):
    tiles = DashboardTileSerializer(
        many=True,
        help_text="Created dashboard widget tiles in request order.",
    )


class UpdateDashboardWidgetsBatchResponseSerializer(serializers.Serializer):
    tiles = DashboardTileSerializer(
        many=True,
        help_text="Updated dashboard widget tiles in request order.",
    )


class DashboardBasicSerializer(
    SearchMatchTypeSerializerMixin,
    TaggedItemSerializerMixin,
    serializers.ModelSerializer,
    UserPermissionsSerializerMixin,
    UserAccessControlSerializerMixin,
):
    created_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    access_control_version = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)
    last_viewed_at = serializers.DateTimeField(read_only=True, required=False, allow_null=True)
    folder = serializers.SerializerMethodField(
        help_text=(
            "Path of the project-tree folder this dashboard is filed under in the file system, "
            "e.g. 'Unfiled/Dashboards'. An empty string means the project root; null means the "
            "dashboard has no file system entry. The dashboard's own name is not part of the path."
        ),
    )

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "pinned",
            "created_at",
            "created_by",
            "last_accessed_at",
            "last_viewed_at",
            "folder",
            "is_shared",
            "deleted",
            "creation_mode",
            "tags",
            "restriction_level",
            "effective_restriction_level",
            "effective_privilege_level",
            "user_access_level",
            "access_control_version",
            "last_refresh",
            "team_id",
            "search_match_type",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "name": {"help_text": "Name of the dashboard."},
            "description": {"help_text": "Description of the dashboard."},
            "pinned": {"help_text": "Whether the dashboard is pinned to the top of the list."},
            "restriction_level": {"help_text": "Controls who can edit the dashboard."},
        }

    def get_effective_restriction_level(self, dashboard: Dashboard) -> Dashboard.RestrictionLevel:
        if self.context.get("is_shared"):
            return Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        return self.user_permissions.dashboard(dashboard).effective_restriction_level

    def get_effective_privilege_level(self, dashboard: Dashboard) -> Dashboard.PrivilegeLevel:
        if self.context.get("is_shared"):
            return Dashboard.PrivilegeLevel.CAN_VIEW
        return self.user_permissions.dashboard(dashboard).effective_privilege_level

    def get_access_control_version(self, dashboard: Dashboard) -> str:
        # This effectively means that the dashboard they are using the old dashboard permissions
        if dashboard.restriction_level > Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            return "v1"
        return "v2"

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_folder(self, dashboard: Dashboard) -> str | None:
        # Don't expose the project-tree location to anonymous viewers of a publicly shared dashboard —
        # the folder name can encode internal organisational structure.
        if self.context.get("is_shared"):
            return None
        # `_folder_path` is annotated on DashboardsViewSet.dangerously_get_queryset (all actions).
        # The file system path's last segment is the dashboard's own name; the folder is everything above it.
        path = getattr(dashboard, "_folder_path", None)
        if not path:
            return None
        return join_path(split_path(path)[:-1])


class DashboardMetadataSerializer(DashboardBasicSerializer):
    filters = serializers.SerializerMethodField()
    variables = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    access_control_version = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)
    breakdown_colors = serializers.JSONField(required=False, help_text="Custom color mapping for breakdown values.")
    data_color_theme_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="ID of the color theme used for chart visualizations."
    )
    quick_filter_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="List of quick filter IDs associated with this dashboard",
    )
    persisted_filters = serializers.SerializerMethodField()
    persisted_variables = serializers.SerializerMethodField()

    class Meta:
        model = Dashboard
        fields = DASHBOARD_SHARED_FIELDS
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared", "user_access_level"]

    def get_filters(self, dashboard: Dashboard) -> dict:
        request = self.context.get("request")
        return filters_override_requested_by_client(request, dashboard)

    def get_variables(self, dashboard: Dashboard) -> dict | None:
        request = self.context.get("request")
        return variables_override_requested_by_client(request, dashboard, list(self.context["insight_variables"]))

    def get_persisted_filters(self, dashboard: Dashboard) -> dict | None:
        return dashboard.filters if dashboard.filters else None

    def get_persisted_variables(self, dashboard: Dashboard) -> dict | None:
        return dashboard.variables if dashboard.variables else None

    def to_representation(self, instance: Dashboard) -> ReturnDict:
        ret = super().to_representation(instance)
        if ret.get("quick_filter_ids") is None:
            ret["quick_filter_ids"] = []
        return ret

    def _filter_out_non_existing_quick_filter_ids(self, quick_filter_ids: list[str], team_id: int) -> list[str]:
        existing_quick_filter_ids = {
            str(uid)
            for uid in QuickFilter.objects.filter(team_id=team_id, id__in=quick_filter_ids).values_list("id", flat=True)
        }
        return [qf_id for qf_id in quick_filter_ids if qf_id in existing_quick_filter_ids]

    def validate_quick_filter_ids(self, value: list[str] | None) -> list[str]:
        if not value:
            return []

        normalized = []
        for v in value:
            try:
                normalized.append(str(uuid.UUID(v)))
            except ValueError:
                raise serializers.ValidationError(f"Invalid UUID: {v}")

        valid_ids = self._filter_out_non_existing_quick_filter_ids(normalized, self.context["get_team"]().id)
        if len(valid_ids) != len(normalized):
            missing = [v for v in normalized if v not in valid_ids]
            raise serializers.ValidationError(f"Quick filters not found: {', '.join(missing)}")

        return normalized


def _count_active_widget_tiles(dashboard: Dashboard) -> int:
    return dashboard.tiles.filter(widget_id__isnull=False).exclude(deleted=True).count()


def _check_dashboard_widget_count_limit(*, dashboard: Dashboard, user: User) -> None:
    check_count_limit(
        team=dashboard.team,
        key=LimitKey.MAX_WIDGETS_PER_DASHBOARD,
        current_count=_count_active_widget_tiles(dashboard),
        user=user,
    )


def _tile_type_and_widget_type(tile: DashboardTile) -> tuple[str, str | None]:
    if tile.text_id is not None:
        return "text", None
    if tile.button_tile_id is not None:
        return "button", None
    if tile.widget_id is not None:
        widget_type = tile.widget.widget_type if tile.widget is not None else None
        return "widget", widget_type
    if tile.insight_id is not None:
        return "insight", None
    raise ValueError("Dashboard tile has no related content for analytics")


def _report_dashboard_tile_added(
    *,
    user: User,
    dashboard: Dashboard,
    tile_type: str,
    request: Request | None = None,
    widget_type: str | None = None,
    tile: DashboardTile | None = None,
) -> None:
    properties: dict[str, Any] = {
        "tile_type": tile_type,
        "insight_type": None,
        "dashboard_id": dashboard.id,
    }
    if widget_type is not None:
        properties["widget_type"] = widget_type

    report_user_action(
        user,
        "dashboard tile added",
        properties,
        team=dashboard.team,
        request=request,
    )

    if widget_type is None:
        return

    widget_properties: dict[str, Any] = {
        "widget_type": widget_type,
        "dashboard_id": dashboard.id,
        "dashboard_widget_count": _count_active_widget_tiles(dashboard),
    }
    feature_enabled = get_widget_feature_enabled(widget_type, dashboard.team)
    if feature_enabled is not None:
        # False means the user lands on the widget's setup/custom view rather than real data.
        widget_properties["feature_enabled"] = feature_enabled
    if tile is not None:
        widget_properties["tile_id"] = tile.id
        if tile.widget_id is not None:
            widget_properties["widget_id"] = str(tile.widget_id)

    report_user_action(
        user,
        "dashboard widget added",
        widget_properties,
        team=dashboard.team,
        request=request,
    )


def _report_dashboard_tile_removed(
    *,
    user: User,
    dashboard: Dashboard,
    tile: DashboardTile,
    request: Request | None = None,
) -> None:
    tile_type, widget_type = _tile_type_and_widget_type(tile)
    insight_type = _get_insight_type(tile.insight) if tile.insight is not None else None
    properties: dict[str, Any] = {
        "tile_type": tile_type,
        "insight_type": insight_type,
        "dashboard_id": dashboard.id,
    }
    if widget_type is not None:
        properties["widget_type"] = widget_type

    report_user_action(
        user,
        "dashboard tile removed",
        properties,
        team=dashboard.team,
        request=request,
    )

    if widget_type is None:
        return

    widget_properties: dict[str, Any] = {
        "widget_type": widget_type,
        "dashboard_id": dashboard.id,
        "tile_id": tile.id,
    }
    if tile.widget_id is not None:
        widget_properties["widget_id"] = str(tile.widget_id)

    report_user_action(
        user,
        "dashboard widget removed",
        widget_properties,
        team=dashboard.team,
        request=request,
    )


def _report_dashboard_widget_updated(
    *,
    user: User,
    dashboard: Dashboard,
    tile: DashboardTile,
    fields_changed: builtins.list[str],
    request: Request | None = None,
) -> None:
    # Fired only by the dedicated widgets/batch_update endpoint, so it doubles as the signal for
    # whether agents reach for this path rather than the generic dashboard PATCH.
    if tile.widget is None:
        return
    properties: dict[str, Any] = {
        "widget_type": tile.widget.widget_type,
        "dashboard_id": dashboard.id,
        "tile_id": tile.id,
        "fields_changed": fields_changed,
    }
    if tile.widget_id is not None:
        properties["widget_id"] = str(tile.widget_id)

    report_user_action(
        user,
        "dashboard widget updated",
        properties,
        team=dashboard.team,
        request=request,
    )


class DashboardSerializer(DashboardMetadataSerializer):
    tiles = serializers.SerializerMethodField()
    use_template = serializers.CharField(
        write_only=True,
        allow_blank=True,
        required=False,
        help_text="Template key to create the dashboard from a predefined template.",
    )
    use_dashboard = serializers.IntegerField(
        write_only=True,
        allow_null=True,
        required=False,
        help_text="ID of an existing dashboard to duplicate.",
    )
    delete_insights = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text="When deleting, also delete insights that are only on this dashboard.",
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Dashboard
        fields = [
            *DASHBOARD_SHARED_FIELDS,
            "tiles",
            "use_template",
            "use_dashboard",
            "delete_insights",
            "_create_in_folder",
        ]
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared", "user_access_level"]

    def validate_filters(self, value) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be a dictionary")

        return value

    def validate_variables(self, value) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Variables must be a dictionary")

        return value

    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="POST")
    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team_id = self.context["team_id"]
        team = self.context["get_team"]()
        current_count = Dashboard.objects.filter(team_id=team_id, deleted=False).count()
        check_count_limit(
            team=team,
            key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
            current_count=current_count,
            user=request.user,
        )
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data.pop("delete_insights", None)  # not used during creation
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        existing_dashboard: Dashboard | None = None
        user_access_control = UserAccessControl(user=cast(User, request.user), team=team)
        if use_dashboard:
            try:
                existing_dashboard = Dashboard.objects.get(
                    id=use_dashboard, team__project_id=self.context["get_team"]().project_id
                )
            except Dashboard.DoesNotExist:
                raise serializers.ValidationError({"use_dashboard": "Invalid value provided"})

            # Duplicating a dashboard reads and copies all of its content (filters, variables, tiles, insights),
            # so the caller must have at least viewer access to the source — mirrors the copy_tile/move_tile checks.
            if not user_access_control.check_access_level_for_object(existing_dashboard, "viewer"):
                raise exceptions.PermissionDenied("You don't have permission to view the source dashboard.")

        request_filters = request.data.get("filters")
        if request_filters:
            if not isinstance(request_filters, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            filters = request_filters
        elif existing_dashboard:
            filters = existing_dashboard.filters
        else:
            filters = {}

        if existing_dashboard and existing_dashboard.variables:
            validated_data["variables"] = existing_dashboard.variables

        if existing_dashboard and existing_dashboard.breakdown_colors:
            validated_data["breakdown_colors"] = existing_dashboard.breakdown_colors

        if existing_dashboard and existing_dashboard.data_color_theme_id:
            validated_data["data_color_theme_id"] = existing_dashboard.data_color_theme_id

        if existing_dashboard and existing_dashboard.quick_filter_ids:
            validated_data["quick_filter_ids"] = self._filter_out_non_existing_quick_filter_ids(
                existing_dashboard.quick_filter_ids, team_id
            )

        if use_template:
            # Create the dashboard and apply the template together so a tile failing partway through
            # rolls back the whole dashboard rather than leaving a half-populated, corrupt one behind.
            try:
                with transaction.atomic():
                    dashboard = Dashboard.objects.create(team_id=team_id, filters=filters, **validated_data)
                    create_dashboard_from_template(
                        use_template,
                        dashboard,
                        cast(User, request.user),
                        user_access_control=user_access_control,
                    )
            except AttributeError as error:
                logger.error(
                    "dashboard_create.create_from_template_failed",
                    team_id=team_id,
                    template=use_template,
                    error=error,
                    exc_info=True,
                )
                raise serializers.ValidationError({"use_template": f"Invalid template provided: {use_template}"})
            except exceptions.APIException:
                # Already a clean 4xx (e.g. widget/tile validation); the dashboard has been rolled back,
                # so let the specific error surface unchanged.
                raise
            except Exception as error:
                # Any other failure while building tiles has now been rolled back; surface a clean
                # error instead of a 500 with a corrupt dashboard left in the database.
                logger.exception(
                    "dashboard_create.create_from_template_failed",
                    team_id=team_id,
                    template=use_template,
                    error=error,
                )
                raise serializers.ValidationError(
                    {"use_template": f"Failed to create dashboard from template: {use_template}"}
                )
        else:
            dashboard = Dashboard.objects.create(team_id=team_id, filters=filters, **validated_data)

            if existing_dashboard:
                existing_tiles = (
                    DashboardTile.objects.filter(dashboard=existing_dashboard)
                    .exclude(deleted=True)
                    .select_related("insight", "text", "button_tile", "widget")
                )
                duplicate_tiles = self.initial_data.get("duplicate_tiles", False)
                for existing_tile in existing_tiles:
                    # Widget tiles move with their widget row; other tiles re-link shared insight/text/button rows.
                    if duplicate_tiles or existing_tile.widget_id is not None:
                        self._deep_duplicate_tiles(dashboard, existing_tile, user_access_control)
                    else:
                        existing_tile.copy_to_dashboard(dashboard)

        # Manual tag creation since this create method doesn't call super()
        self._attempt_set_tags(tags, dashboard)

        report_user_action(
            request.user,
            "dashboard created",
            {
                **dashboard.get_analytics_metadata(),
                "from_template": bool(use_template),
                "template_key": use_template,
                "duplicated": bool(use_dashboard),
                "duplicated_from_dashboard_id": use_dashboard,
            },
            team=dashboard.team,
            request=request,
        )

        return dashboard

    def _deep_duplicate_tiles(
        self, dashboard: Dashboard, existing_tile: DashboardTile, user_access_control: UserAccessControl
    ) -> None:
        if existing_tile.insight:
            # Deep duplication serializes and recreates the source insight, so the caller must have viewer
            # access to that specific insight — an insight can be restricted independently of its dashboard.
            if not user_access_control.check_access_level_for_object(existing_tile.insight, "viewer"):
                raise exceptions.PermissionDenied(
                    "You don't have permission to view one of the source dashboard's insights."
                )

            new_data = {
                **InsightSerializer(existing_tile.insight, context=self.context).data,
                "id": None,  # to create a new Insight
                "last_refresh": now(),
                "name": (existing_tile.insight.name + " (Copy)") if existing_tile.insight.name else None,
            }
            new_data.pop("dashboards", None)
            new_tags = new_data.pop("tags", None)
            insight_serializer = InsightSerializer(data=new_data, context=self.context)
            insight_serializer.is_valid()
            insight_serializer.save()
            insight = cast(Insight, insight_serializer.instance)

            # Create new insight's tags separately. Force create tags on dashboard duplication.
            self._attempt_set_tags(new_tags, insight)

            DashboardTile.objects.create(
                dashboard=dashboard,
                team_id=dashboard.team_id,
                insight=insight,
                layouts=existing_tile.layouts,
                color=existing_tile.color,
                filters_overrides=existing_tile.filters_overrides,
                show_description=existing_tile.show_description,
                transparent_background=existing_tile.transparent_background,
            )
        elif existing_tile.text:
            new_data = {
                **TextSerializer(existing_tile.text, context=self.context).data,
                "id": None,  # to create a new Text
            }
            new_data.pop("dashboards", None)
            text_serializer = TextSerializer(data=new_data, context=self.context)
            text_serializer.is_valid()
            text_serializer.save()
            text = cast(Text, text_serializer.instance)
            DashboardTile.objects.create(
                dashboard=dashboard,
                team_id=dashboard.team_id,
                text=text,
                layouts=existing_tile.layouts,
                color=existing_tile.color,
                filters_overrides=existing_tile.filters_overrides,
                show_description=existing_tile.show_description,
                transparent_background=existing_tile.transparent_background,
            )
        elif existing_tile.button_tile:
            new_data = {
                **ButtonTileSerializer(existing_tile.button_tile, context=self.context).data,
                "id": None,
            }
            new_data.pop("dashboards", None)
            button_tile_serializer = ButtonTileSerializer(data=new_data, context=self.context)
            button_tile_serializer.is_valid()
            button_tile_serializer.save()
            button_tile = cast(ButtonTile, button_tile_serializer.instance)
            DashboardTile.objects.create(
                dashboard=dashboard,
                team_id=dashboard.team_id,
                button_tile=button_tile,
                layouts=existing_tile.layouts,
                color=existing_tile.color,
                filters_overrides=existing_tile.filters_overrides,
                show_description=existing_tile.show_description,
                transparent_background=existing_tile.transparent_background,
            )
        elif existing_tile.widget:
            request = self.context["request"]
            DashboardSerializer._clone_widget_tile_to_dashboard(
                existing_tile,
                dashboard,
                cast(User, request.user),
            )

    @staticmethod
    def _clone_widget_tile_to_dashboard(
        source_tile: DashboardTile,
        destination: Dashboard,
        user: User,
        *,
        append_copy_suffix: bool = True,
    ) -> DashboardTile:
        if source_tile.widget is None:
            raise serializers.ValidationError("Tile is not a widget tile.")

        _check_dashboard_widget_count_limit(dashboard=destination, user=user)

        widget_name = source_tile.widget.name
        duplicate_name: str | None
        if append_copy_suffix and widget_name:
            duplicate_name = f"{widget_name} (Copy)"
        else:
            duplicate_name = widget_name

        widget = DashboardWidget.objects.create(
            team_id=destination.team_id,
            widget_type=source_tile.widget.widget_type,
            name=duplicate_name,
            description=source_tile.widget.description,
            config=source_tile.widget.config,
            created_by=user,
            last_modified_by=user,
        )
        return DashboardTile.objects.create(
            dashboard=destination,
            team_id=destination.team_id,
            widget=widget,
            layouts=source_tile.layouts,
            color=source_tile.color,
            filters_overrides=source_tile.filters_overrides,
            show_description=source_tile.show_description,
            transparent_background=source_tile.transparent_background,
        )

    @staticmethod
    def _check_widget_tile_product_access(
        widget: DashboardWidget,
        user_access_control: UserAccessControl,
    ) -> None:
        check_widget_tile_product_access(widget, user_access_control)

    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="PATCH")
    def update(self, instance: Dashboard, validated_data: dict, *args: Any, **kwargs: Any) -> Dashboard:
        can_user_restrict = self.user_permissions.dashboard(instance).can_restrict
        if "restriction_level" in validated_data and not can_user_restrict:
            raise exceptions.PermissionDenied(
                "Only the dashboard owner and project admins have the restriction rights required to change the dashboard's restriction level."
            )

        validated_data.pop("use_template", None)  # Remove attribute if present

        being_undeleted = instance.deleted and "deleted" in validated_data and not validated_data["deleted"]
        if being_undeleted:
            self._undo_delete_related_tiles(instance)

        # Soft-delete transition (false -> true). All channels (web/MCP/API) delete via this PATCH path,
        # so this is the single place to capture deletes. Snapshot tile counts before _delete_related_tiles
        # runs below — otherwise get_analytics_metadata()'s item_count would read 0 post-deletion.
        being_deleted = not instance.deleted and validated_data.get("deleted", False)
        tile_count_at_deletion = instance.tiles.count() if being_deleted else None
        item_count_at_deletion = instance.tiles.exclude(insight=None).count() if being_deleted else None

        initial_data = dict(self.initial_data)

        if validated_data.get("deleted", False):
            self._delete_related_tiles(instance, self.validated_data.get("delete_insights", False))
            from posthog.models.team import Team

            Team.objects.filter(
                primary_dashboard=instance,
                id=instance.team_id,
            ).update(primary_dashboard=None)
            from posthog.models.group_type_mapping import clear_dashboard_from_group_type_mapping

            clear_dashboard_from_group_type_mapping(
                team_id=instance.team_id, dashboard_id=instance.id, project_id=instance.team.project_id
            )

        request_filters = initial_data.get("filters")
        if request_filters:
            if not isinstance(request_filters, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            instance.filters = request_filters

        request_variables = initial_data.get("variables")
        if request_variables:
            if not isinstance(request_variables, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            instance.variables = request_variables

        instance = super().update(instance, validated_data)

        user = cast(User, self.context["request"].user)
        tiles = initial_data.pop("tiles", [])
        for tile_data in tiles:
            tile, created = self._update_tiles(instance, tile_data, user, request=self.context.get("request"))
            # Text and button tiles are always added via PATCH (never during initial dashboard
            # creation), so this update() method is the right place to fire the "tile added"
            # event. The `created` flag from update_or_create ensures we only fire on first
            # insertion, not on subsequent edits to an existing tile.
            if created and tile is not None and "request" in self.context:
                tile_type, widget_type = DashboardSerializer._tile_added_analytics_fields(tile)
                _report_dashboard_tile_added(
                    user=user,
                    dashboard=instance,
                    tile_type=tile_type,
                    widget_type=widget_type,
                    request=self.context["request"],
                    tile=tile,
                )

        duplicate_tiles = initial_data.pop("duplicate_tiles", [])
        if duplicate_tiles:
            user_access_control = UserAccessControl(user=user, team=instance.team)
            for tile_data in duplicate_tiles:
                # nosemgrep: idor-lookup-without-team (scoped via parent viewset get_queryset)
                existing_tile = DashboardTile.objects.get(dashboard=instance, id=tile_data["id"])
                existing_tile.layouts = tile_data.get("layouts", {})
                self._deep_duplicate_tiles(instance, existing_tile, user_access_control)

        if "request" in self.context:
            if being_deleted:
                report_user_action(
                    user,
                    "dashboard deleted",
                    {
                        **instance.get_analytics_metadata(),
                        "item_count": item_count_at_deletion,  # override post-delete 0 with pre-delete snapshot
                        "tile_count": tile_count_at_deletion,
                    },
                    team=instance.team,
                    request=self.context["request"],
                )
            else:
                report_user_action(
                    user,
                    "dashboard updated",
                    instance.get_analytics_metadata(),
                    team=instance.team,
                    request=self.context["request"],
                )

        self.user_permissions.reset_insights_dashboard_cached_results()
        return instance

    # Display-only tile fields that may appear in PATCH payloads. Safe to pass to
    # ``update_or_create`` defaults (used by ``_upsert_tile``) and to
    # ``save(update_fields=...)`` (used by ``_update_existing_tile_display_fields``).
    TILE_DISPLAY_FIELDS = {
        "color",
        "layouts",
        "filters_overrides",
        "show_description",
        "transparent_background",
        "deleted",
    }

    @staticmethod
    def _extract_display_defaults(tile_data: dict) -> dict:
        return {k: tile_data[k] for k in DashboardSerializer.TILE_DISPLAY_FIELDS if k in tile_data}

    @staticmethod
    def _widget_tile_validation_error(exc: serializers.ValidationError) -> serializers.ValidationError:
        detail = exc.detail
        if isinstance(detail, dict) and "widget" in detail and len(detail) == 1:
            return exc
        if isinstance(detail, dict):
            if "widget_type" in detail:
                return serializers.ValidationError({"widget": detail["widget_type"]})
            if "config" in detail:
                return serializers.ValidationError({"widget": detail["config"]})
        return serializers.ValidationError({"widget": detail})

    @staticmethod
    def _validated_patch_widget_payload(widget_json: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = ("id", "widget_type", "config", "name", "description")
        payload = {key: widget_json[key] for key in allowed_keys if key in widget_json}
        serializer = DashboardPatchWidgetSerializer(data=payload)
        if not serializer.is_valid():
            raise serializers.ValidationError({"widget": serializer.errors})
        return cast(dict[str, Any], serializer.validated_data)

    @staticmethod
    def _apply_patch_widget_update(
        *,
        widget: DashboardWidget,
        widget_data: dict[str, Any],
        user: User,
        user_access_control: UserAccessControl,
        dashboard: Dashboard,
        request: Request | None = None,
    ) -> None:
        DashboardSerializer._check_widget_tile_product_access(widget, user_access_control)
        patch_widget_type = widget_data.get("widget_type")
        if patch_widget_type is not None and str(patch_widget_type) != widget.widget_type:
            raise serializers.ValidationError({"widget": "widget_type cannot be changed."})

        previous_widget_filters = extract_widget_filters(widget.widget_type, widget.config)
        if "config" in widget_data:
            widget.config = validate_widget_config(
                widget.widget_type,
                widget_data["config"],
            )
        if "name" in widget_data:
            widget.name = widget_data["name"] or None
        if "description" in widget_data:
            widget.description = widget_data["description"]
        widget.last_modified_by = user
        widget.last_modified_at = now()
        widget.save()

        new_widget_filters = extract_widget_filters(widget.widget_type, widget.config)
        if "config" in widget_data and new_widget_filters != previous_widget_filters:
            report_user_action(
                user,
                "dashboard widget filters updated",
                {
                    "widget_type": widget.widget_type,
                    "dashboard_id": dashboard.id,
                    "widget_id": str(widget.id),
                    "filters_count": count_active_widget_filters(widget.widget_type, widget.config),
                },
                team=dashboard.team,
                request=request,
            )

    @staticmethod
    def _upsert_tile(instance: Dashboard, tile_data: dict, **extra_defaults: Any) -> tuple[DashboardTile, bool]:
        tile_defaults = DashboardSerializer._extract_display_defaults(tile_data)
        # nosemgrep: idor-lookup-without-team -- dashboard=instance constrains to team
        return DashboardTile.objects_including_soft_deleted.update_or_create(
            id=tile_data.get("id", None),
            dashboard=instance,
            defaults={**tile_defaults, **extra_defaults, "dashboard": instance},
        )

    @staticmethod
    def _update_existing_tile_display_fields(instance: Dashboard, tile_data: dict) -> tuple[DashboardTile | None, bool]:
        """Update display fields on an existing tile, or skip silently if the id is unknown.

        A display-only payload carries no insight/text/button_tile FK, so it cannot satisfy
        the ``dash_tile_exactly_one_related_object`` CHECK constraint if it falls through to
        an INSERT. ``update_or_create`` here used to 500 whenever the frontend posted a stale
        tile id (cross-dashboard contamination, hard-deleted tiles, races). Never INSERT here.

        Returns the updated tile and whether this payload transitioned it to soft-deleted.
        """
        tile_id = tile_data.get("id")
        if tile_id is None:
            return None, False

        tile_defaults = DashboardSerializer._extract_display_defaults(tile_data)
        if not tile_defaults:
            return None, False

        existing = DashboardTile.objects_including_soft_deleted.filter(
            id=tile_id, dashboard=instance, dashboard__team_id=instance.team_id
        ).first()
        if existing is None:
            logger.warning(
                "dashboard_layout_patch_unknown_tile_skipped",
                team_id=instance.team_id,
                dashboard_id=instance.id,
                tile_id=tile_id,
                payload_fields=sorted(tile_defaults.keys()),
            )
            return None, False

        became_deleted = bool(tile_defaults.get("deleted")) and not existing.deleted
        for attr, val in tile_defaults.items():
            setattr(existing, attr, val)
        # update_fields scopes the UPDATE to only the columns we changed, so concurrent writes
        # to other columns aren't clobbered by our stale read. save() (vs queryset.update())
        # keeps the post_save signal that sync_dashboard_tile listens to for cache invalidation.
        existing.save(update_fields=list(tile_defaults.keys()))
        return existing, became_deleted

    @staticmethod
    def _tile_added_analytics_fields(tile: DashboardTile) -> tuple[str, str | None]:
        return _tile_type_and_widget_type(tile)

    @staticmethod
    def _update_tiles(
        instance: Dashboard, tile_data: dict, user: User, request: Request | None = None
    ) -> tuple[DashboardTile | None, bool]:
        """Returns the upserted tile and whether it was newly created, or (None, False) for display-only updates."""
        tile_data.pop("is_cached", None)  # read only field
        tile_data.pop("order", None)  # read only field

        if tile_data.get("text", None):
            text_json: dict = tile_data.get("text", {})
            created_by_json = text_json.get("created_by", None)
            if created_by_json:
                last_modified_by = user
                try:
                    created_by = User.objects.get(
                        id=created_by_json.get("id"),
                        organization_membership__organization_id=instance.team.organization_id,
                    )
                except User.DoesNotExist:
                    raise serializers.ValidationError("User not found in this organization.")
            else:
                created_by = user
                last_modified_by = None

            text_data = {**tile_data["text"], "team": instance.team_id}
            text_serializer = TextSerializer(data=text_data)
            if not text_serializer.is_valid():
                raise serializers.ValidationError({"text": text_serializer.errors})

            validated_data = text_serializer.validated_data
            validated_data["created_by"] = created_by
            validated_data["last_modified_by"] = last_modified_by
            validated_data["last_modified_at"] = now()

            existing_text_id = text_json.get("id", None)
            if existing_text_id:
                try:
                    text = Text.objects.get(id=existing_text_id, team_id=instance.team_id)
                    if not DashboardTile.objects.filter(dashboard=instance, text_id=existing_text_id).exists():
                        raise serializers.ValidationError({"text": "Text tile not found."})
                    for attr, val in validated_data.items():
                        setattr(text, attr, val)
                    text.save()
                except Text.DoesNotExist:
                    raise serializers.ValidationError({"text": "Text tile not found in this team."})
            else:
                text = Text.objects.create(**validated_data)
            tile, created = DashboardSerializer._upsert_tile(instance, tile_data, text=text)
            return tile, created
        elif tile_data.get("button_tile", None):
            button_tile_json: dict = tile_data.get("button_tile", {})
            created_by_json = button_tile_json.get("created_by", None)
            if created_by_json:
                last_modified_by = user
                try:
                    created_by = User.objects.get(
                        id=created_by_json.get("id"),
                        organization_membership__organization_id=instance.team.organization_id,
                    )
                except User.DoesNotExist:
                    raise serializers.ValidationError("User not found in this organization.")
            else:
                created_by = user
                last_modified_by = None

            button_tile_data = {**tile_data["button_tile"], "team": instance.team_id}
            button_tile_serializer = ButtonTileSerializer(data=button_tile_data)
            if not button_tile_serializer.is_valid():
                raise serializers.ValidationError({"button_tile": button_tile_serializer.errors})

            validated_data = button_tile_serializer.validated_data
            validated_data["created_by"] = created_by
            validated_data["last_modified_by"] = last_modified_by
            validated_data["last_modified_at"] = now()

            existing_button_id = button_tile_json.get("id", None)
            if existing_button_id:
                try:
                    button_tile = ButtonTile.objects.get(id=existing_button_id, team_id=instance.team_id)
                    if not DashboardTile.objects.filter(dashboard=instance, button_tile_id=existing_button_id).exists():
                        raise serializers.ValidationError({"button_tile": "Button tile not found."})
                    for attr, val in validated_data.items():
                        setattr(button_tile, attr, val)
                    button_tile.save()
                except ButtonTile.DoesNotExist:
                    raise serializers.ValidationError({"button_tile": "Button tile not found in this team."})
            else:
                button_tile = ButtonTile.objects.create(**validated_data)
            tile, created = DashboardSerializer._upsert_tile(instance, tile_data, button_tile=button_tile)
            return tile, created
        elif tile_data.get("widget", None):
            widget_json: dict = tile_data.get("widget", {})
            widget_data = DashboardSerializer._validated_patch_widget_payload(widget_json)

            if not dashboard_widgets_enabled(team=instance.team, user=user):
                raise serializers.ValidationError({"widget": "Dashboard widgets are not enabled for this project."})

            user_access_control = UserAccessControl(user=user, team=instance.team)
            existing_widget_id = widget_data.get("id")

            if existing_widget_id:
                try:
                    widget = DashboardWidget.objects.get(id=existing_widget_id, team_id=instance.team_id)
                    if not DashboardTile.objects.filter(dashboard=instance, widget_id=existing_widget_id).exists():
                        raise serializers.ValidationError({"widget": "Widget tile not found."})
                    DashboardSerializer._apply_patch_widget_update(
                        widget=widget,
                        widget_data=widget_data,
                        user=user,
                        user_access_control=user_access_control,
                        dashboard=instance,
                        request=request,
                    )
                except DashboardWidget.DoesNotExist:
                    raise serializers.ValidationError({"widget": "Widget not found in this team."})
            else:
                try:
                    canonical_widget_type, config = prepare_widget_tile_create(
                        team=instance.team,
                        widget_type=str(widget_data["widget_type"]),
                        config=widget_data.get("config", {}),
                        user=user,
                        user_access_control=user_access_control,
                    )
                except serializers.ValidationError as exc:
                    raise DashboardSerializer._widget_tile_validation_error(exc) from exc

                _check_dashboard_widget_count_limit(dashboard=instance, user=user)

                widget = DashboardWidget.objects.create(
                    team_id=instance.team_id,
                    widget_type=canonical_widget_type,
                    name=widget_data.get("name") or None,
                    description=widget_data.get("description", ""),
                    config=config,
                    created_by=user,
                    last_modified_by=user,
                )
            tile, created = DashboardSerializer._upsert_tile(instance, tile_data, widget=widget)
            return tile, created
        elif (
            "deleted" in tile_data
            or "color" in tile_data
            or "layouts" in tile_data
            or "filters_overrides" in tile_data
            or "show_description" in tile_data
            or "transparent_background" in tile_data
        ):
            tile_data.pop("insight", None)  # don't ever update insight tiles here
            updated_tile, became_deleted = DashboardSerializer._update_existing_tile_display_fields(instance, tile_data)
            # The dashboard UI soft-deletes tiles through this PATCH path rather than the
            # delete_tile endpoint, so removal analytics must fire here too.
            if became_deleted and updated_tile is not None:
                _report_dashboard_tile_removed(
                    user=user,
                    dashboard=instance,
                    tile=updated_tile,
                    request=request,
                )

        return None, False

    @staticmethod
    def _delete_related_tiles(instance: Dashboard, delete_related_insights: bool) -> None:
        if delete_related_insights:
            # Count only non-deleted tiles. Note: deleted is nullable, so we exclude deleted=True
            # rather than filtering for deleted=False (which would miss deleted=None)
            insight_ids_to_delete = list(
                instance.tiles.filter(insight__isnull=False)
                .annotate(
                    insight_tile_count=Count(
                        "insight__dashboard_tiles",
                        filter=~Q(insight__dashboard_tiles__deleted=True),
                    )
                )
                .filter(insight_tile_count=1)
                .values_list("insight_id", flat=True)
            )

            if insight_ids_to_delete:
                # nosemgrep: idor-lookup-without-team
                Insight.objects.filter(id__in=insight_ids_to_delete).update(deleted=True)
                # Bulk update bypasses signals, so the FileSystemSyncMixin can't prune the
                # corresponding FileSystem rows. Without this, stale entries linger in the
                # Recents sidebar and clicking them lands on an "Insight not found" page.
                DashboardSerializer._sync_filesystem_for_insights(insight_ids_to_delete, instance.team_id)

        DashboardTile.objects_including_soft_deleted.filter(dashboard__id=instance.id).update(deleted=True)

    @staticmethod
    def _undo_delete_related_tiles(instance: Dashboard) -> None:
        DashboardTile.objects_including_soft_deleted.filter(dashboard__id=instance.id).update(deleted=False)
        # The default Insight manager excludes deleted=True, so traversing tile.insight returns None
        # for soft-deleted rows. Query the unfiltered manager directly to find the insights that
        # need to be restored alongside the dashboard.
        insights_to_undelete = list(
            Insight.objects_including_soft_deleted.filter(
                dashboard_tiles__dashboard_id=instance.id, deleted=True
            ).distinct()
        )
        for insight in insights_to_undelete:
            insight.deleted = False
        if insights_to_undelete:
            Insight.objects_including_soft_deleted.bulk_update(insights_to_undelete, ["deleted"])
            # bulk_update also bypasses signals — re-sync FileSystem so restored insights reappear.
            DashboardSerializer._sync_filesystem_for_insights(
                [insight.id for insight in insights_to_undelete], instance.team_id
            )

    @staticmethod
    def _sync_filesystem_for_insights(insight_ids: list[int], team_id: int) -> None:
        """Re-run FileSystem sync for insights whose ``deleted`` flag was changed via bulk update."""
        # The default Insight manager excludes deleted=True, so use the unfiltered manager —
        # this helper is invoked specifically after bulk deletes/undeletes and must see both.
        insights = Insight.objects_including_soft_deleted.filter(id__in=insight_ids, team_id=team_id).select_related(
            "team"
        )
        for insight in insights:
            fs_data = insight.get_file_system_representation()
            try:
                if fs_data.should_delete:
                    delete_file(team=insight.team, file_type=fs_data.type, ref=fs_data.ref, surface=fs_data.surface)
                else:
                    create_or_update_file(
                        team=insight.team,
                        base_folder=fs_data.base_folder,
                        name=fs_data.name,
                        file_type=fs_data.type,
                        ref=fs_data.ref,
                        href=fs_data.href,
                        meta=fs_data.meta,
                        created_at=fs_data.meta.get("created_at") or insight.created_at,
                        created_by_id=fs_data.meta.get("created_by") or insight.created_by_id,
                        surface=fs_data.surface,
                    )
            except Exception as exc:
                # Mirror the signal-handler stance: never raise from sync, but surface it.
                capture_exception(exc, additional_properties={"insight_id": insight.id, "team_id": team_id})

    @tracer.start_as_current_span("DashboardSerializer.get_tiles")
    def get_tiles(self, dashboard: Dashboard) -> Optional[list[ReturnDict]]:
        if self.context["view"].action == "list":
            return None

        # used by insight serializer to load insight filters in correct context
        self.context.update({"dashboard": dashboard})

        serialized_tiles: list[ReturnDict] = []

        tiles = DashboardTile.dashboard_queryset(dashboard.tiles.all()).prefetch_related(
            # Used by the shared-insight force_blocking gate in `posthog/api/insight.py` to avoid an
            # N+1 lookup of last_refresh per tile on shared dashboard renders.
            "caching_states",
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            ),
            Prefetch(
                "insight__alertconfiguration_set",
                queryset=AlertConfiguration.objects.select_related("created_by"),
                to_attr="_prefetched_alerts",
            ),
        )
        self.user_permissions.set_preloaded_dashboard_tiles(list(tiles))

        team = self.context["get_team"]()
        chained_tile_refresh_enabled = posthoganalytics.feature_enabled(
            "chained_dashboard_tile_refresh",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
        )

        layout_size = "sm"  # default layout size

        # Sort tiles by layout to ensure insights are computed in order of appearance on dashboard
        # Use the specified layout size to get the correct order for the current viewport
        sorted_tiles = DashboardTile.sort_tiles_by_layout(tiles, layout_size)

        with task_chain_context() if chained_tile_refresh_enabled else nullcontext():
            # Handle case where there are no tiles
            if not sorted_tiles:
                return []

            for order, tile in enumerate(sorted_tiles):
                order, tile_data = serialize_tile_with_context(tile, order, self.context)
                serialized_tiles.append(cast(ReturnDict, tile_data))

        return serialized_tiles

    def validate(self, data):
        if data.get("use_dashboard", None) and data.get("use_template", None):
            raise serializers.ValidationError("`use_dashboard` and `use_template` cannot be used together")
        return data

    def _update_creation_mode(self, validated_data, use_template: str, use_dashboard: int):
        if use_template:
            return {**validated_data, "creation_mode": "template"}
        if use_dashboard:
            return {**validated_data, "creation_mode": "duplicate"}

        return {**validated_data, "creation_mode": "default"}


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. Match against dashboard `name`, `description`, and tag names. Returns exact "
                    "(case-insensitive substring) matches only; if no exact match exists, returns similar "
                    "(fuzzy trigram — typos, transpositions, prefix-as-you-type) matches instead. Results "
                    "are then ordered by relevance, then pinned status, then name; each result's `search_match_type` is "
                    "`exact` or `similar`. When omitted, dashboards are ordered by pinned status then "
                    "alphabetical name. Capped at 200 characters; longer queries return a 400 error."
                ),
            ),
            OpenApiParameter(
                "folder",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. Return only dashboards filed directly in this project-tree folder, e.g. "
                    "'Unfiled/Dashboards'. An empty string matches dashboards at the project root. Nested "
                    "sub-folders are not included."
                ),
            ),
        ],
    ),
    partial_update=extend_schema(request=PatchedDashboardOpenApiSerializer),
)
class DashboardsViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "dashboard"
    # Record a tags change per dashboard when bulk_update_tags mutates it, matching the single-object path.
    bulk_tag_activity_scope = "Dashboard"
    queryset = Dashboard.objects_including_soft_deleted.order_by("-pinned", "name")
    permission_classes = [CanEditDashboard]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    TEMPLATE_MAP = {
        "llm-analytics": get_ai_observability_default_template,
        "mcp-analytics": get_mcp_analytics_default_template,
    }

    @tracer.start_as_current_span("DashboardViewSet.get_serializer_context")
    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["insight_variables"] = InsightVariable.objects.filter(team=self.team).all()

        return context

    def get_serializer_class(self) -> type[BaseSerializer]:
        return DashboardBasicSerializer if self.action == "list" else DashboardSerializer

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = super().filter_queryset(queryset)

        search = self.request.query_params.get("search")
        if search:
            if len(search) > MAX_SEARCH_LENGTH:
                raise serializers.ValidationError(
                    {"search": f"Search query must be {MAX_SEARCH_LENGTH} characters or fewer."}
                )
            queryset = self._apply_search(queryset, search)

        tags = self.request.query_params.getlist("tags")
        if tags:
            queryset = queryset.filter(tagged_items__tag__name__in=tags).distinct()

        folder = self.request.query_params.get("folder")
        if folder is not None:
            queryset = self._apply_folder_filter(queryset, folder)

        return drop_similar_when_exact_exists(queryset)

    @staticmethod
    def _apply_folder_filter(queryset: QuerySet, folder: str) -> QuerySet:
        # Keep dashboards whose default-surface, non-shortcut file system entry sits *directly* in `folder`
        # (an empty string means the project root). `depth` pins it to direct children so dashboards nested in
        # sub-folders don't leak in, and lets the filter ride the posthog_fs_team_s_typeref index via the
        # correlated ref lookup. Stored paths are already escaped, so the prefix comparison stays segment-safe.
        entries = FileSystem.objects.filter(
            surface_q(DEFAULT_SURFACE),
            team_id=OuterRef("team_id"),
            type="dashboard",
            ref=Cast(OuterRef("id"), output_field=CharField()),
            depth=len(split_path(folder)) + 1 if folder else 1,
        ).exclude(shortcut=True)
        if folder:
            entries = entries.filter(path__startswith=f"{folder}/")
        return queryset.filter(Exists(entries))

    @tracer.start_as_current_span("DashboardViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().list(request, *args, **kwargs)
        # Record search-result cardinality so we can tune MIN_*_TRIGRAM_SIMILARITY from prod
        # telemetry — flag empty results (loosen) and high counts (tighten).
        if request.query_params.get("search"):
            data = response.data if isinstance(response.data, dict) else {}
            results_len = data.get("count", len(data.get("results", [])))
            span = trace.get_current_span()
            span.set_attribute("dashboard.search.result_count", results_len)
            span.set_attribute("dashboard.search.empty", results_len == 0)
        return response

    @staticmethod
    @tracer.start_as_current_span("DashboardViewSet._apply_search")
    def _apply_search(queryset: QuerySet, search: str) -> QuerySet:
        return apply_trigram_search(
            queryset,
            search,
            span_prefix="dashboard.search",
            fields=(NAME_FIELD, DESCRIPTION_FIELD),
            include_tag_search=True,
            tiebreakers=("-pinned", "name"),
        )

    @tracer.start_as_current_span("DashboardViewSet.dangerously_get_queryset")
    def dangerously_get_queryset(self):
        # Dashboards are retrieved under /environments/ because they include team-specific query results,
        # but they are in fact project-level, rather than environment-level
        assert self.team.project_id is not None
        queryset = self.queryset.filter(team__project_id=self.team.project_id)

        if self.request.user.is_authenticated:
            queryset = queryset.alias(
                recent_dashboard_views=FilteredRelation(
                    "team__filesystemviewlog",  # team_id condition comes from "team__"
                    condition=(
                        Q(team__filesystemviewlog__user_id=self.request.user.id)
                        & Q(team__filesystemviewlog__type="dashboard")
                        & Q(team__filesystemviewlog__ref=Cast(F("id"), output_field=CharField()))
                    ),
                )
            ).annotate(last_viewed_at=F("recent_dashboard_views__viewed_at"))
        else:
            queryset = queryset.annotate(last_viewed_at=Value(None, output_field=DateTimeField()))

        # Annotate the project-tree folder each dashboard is filed under, so responses can expose it
        # without an extra round-trip. A single-valued correlated subquery against the file system —
        # backed by the posthog_fs_team_s_typeref index on (team_id, surface, type, ref) — keeps this cheap
        # and avoids the row multiplication a join could cause when shortcuts/multiple surfaces exist.
        # The default surface matches both NULL and "web" rows, so order by id to keep the picked path
        # stable when more than one non-shortcut entry exists for the same dashboard.
        queryset = queryset.annotate(_ref_id=Cast(F("id"), output_field=CharField())).annotate(
            _folder_path=Subquery(
                FileSystem.objects.filter(
                    surface_q(DEFAULT_SURFACE),
                    team_id=OuterRef("team_id"),
                    type="dashboard",
                    ref=OuterRef("_ref_id"),
                )
                .exclude(shortcut=True)
                .order_by("id")
                .values("path")[:1],
                output_field=CharField(),
            )
        )

        include_deleted = False
        if self.action in ("partial_update", "update") and hasattr(self, "request"):
            deleted_value = self.request.data.get("deleted")
            if deleted_value is not None:
                include_deleted = not str_to_bool(deleted_value)

        if not include_deleted:
            # a dashboard can be restored by patching {"deleted": False}
            queryset = queryset.exclude(deleted=True)

        queryset = queryset.prefetch_related("sharingconfiguration_set").select_related("created_by")

        if self.action != "list":
            tiles_prefetch_queryset = DashboardTile.dashboard_queryset(
                DashboardTile.objects.prefetch_related(
                    "caching_states",
                    Prefetch(
                        "insight__dashboards",
                        # nosemgrep: idor-lookup-without-team (scoped via prefetch on team-scoped queryset)
                        queryset=Dashboard.objects.filter(
                            id__in=DashboardTile.objects.values_list("dashboard_id", flat=True)
                        ),
                    ),
                    "insight__dashboard_tiles__dashboard",
                )
            )
            try:
                dashboard_id = self.kwargs["pk"]
                tiles_prefetch_queryset = tiles_prefetch_queryset.filter(dashboard_id=dashboard_id)
            except KeyError:
                # in case there are endpoints that hit this branch but don't have a pk
                pass

            queryset = queryset.prefetch_related(
                # prefetching tiles saves 25 queries per tile on the dashboard
                Prefetch(
                    "tiles",
                    queryset=tiles_prefetch_queryset,
                ),
            )

        # Add access level filtering for list actions
        queryset = self._filter_queryset_by_access_level(queryset)

        # Filter out generated dashboards if requested (for list action only)
        if self.action == "list" and self.request.query_params.get("exclude_generated") == "true":
            queryset = queryset.exclude(name__startswith=GENERATED_DASHBOARD_PREFIX)

        # Allow filtering by creation_mode query param
        creation_mode = self.request.query_params.get("creation_mode")
        if creation_mode:
            queryset = queryset.filter(creation_mode=creation_mode)
        # Filter unlisted dashboards from general list unless explicitly requested
        # Direct ID lookups (detail action) are allowed through retrieve()
        elif self.action == "list":
            queryset = queryset.exclude(creation_mode="unlisted")

        return queryset

    @extend_schema(parameters=[VARIABLES_OVERRIDE_PARAM, FILTERS_OVERRIDE_PARAM])
    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = self.get_object()

        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])
        serializer = DashboardSerializer(dashboard, context=self.get_serializer_context())
        data = serializer.data

        response = Response(data)

        # Track non-web reads (API/MCP/wizard/…) as a distinct event so programmatic
        # reads are measurable without inflating the web-only `dashboard viewed` metric.
        if get_event_source(request) != EventSource.WEB:
            report_user_action(
                request.user,
                "dashboard read",
                {"dashboard_id": dashboard.id, "creation_mode": dashboard.creation_mode},
                team=self.team,
                request=request,
            )

        return response

    # ******************************************
    # /projects/:id/dashboard/:id/stream_tiles
    # ******************************************
    @extend_schema(
        parameters=[
            VARIABLES_OVERRIDE_PARAM,
            FILTERS_OVERRIDE_PARAM,
            OpenApiParameter(
                "layoutSize",
                OpenApiTypes.STR,
                enum=["sm", "xs"],
                description=(
                    "Layout size for tile positioning. 'sm' (default) for standard, 'xs' for mobile. "
                    "The snake_case alias `layout_size` is also accepted for backward compatibility."
                ),
            ),
        ],
    )
    @action(methods=["GET"], detail=True, url_path="stream_tiles")
    def stream_tiles(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered."""
        dashboard = self.get_object()  # This will raise 404 if not found - let it bubble up normally

        # Do all database operations and data loading synchronously first
        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])

        # Prepare metadata with initial tiles
        metadata_serializer = DashboardMetadataSerializer(dashboard, context=self.get_serializer_context())
        metadata_data = metadata_serializer.data

        # Create serializer context for tiles
        context = self.get_serializer_context()
        context.update({"dashboard": dashboard})

        # Get tiles with proper prefetch
        tiles = DashboardTile.dashboard_queryset(dashboard.tiles.all()).prefetch_related(
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            )
        )

        layout_size = self._get_layout_size_from_request(request)

        sorted_tiles = sorted(
            tiles,
            key=lambda tile: (
                tile.layouts.get(layout_size, {}).get("y", 100),
                tile.layouts.get(layout_size, {}).get("x", 100),
            ),
        )

        # Async generator that handles progressive tile serialization and streaming
        async def async_tile_stream_generator() -> AsyncGenerator[bytes]:
            renderer = SafeJSONRenderer()

            try:
                # Serialize the first 2 tiles (or fewer if dashboard has less) for inclusion in metadata
                initial_tiles = []
                initial_tile_count = min(2, len(sorted_tiles))

                for order in range(initial_tile_count):
                    tile = sorted_tiles[order]
                    try:
                        order_result, tile_data = await database_sync_to_async(
                            serialize_tile_with_context, thread_sensitive=True
                        )(tile, order, context)
                        initial_tiles.append(tile_data)
                    except Exception as e:
                        logger.exception(f"Error serializing initial tile {tile.id}: {e}")
                        # Add error tile to initial tiles
                        initial_tiles.append(
                            {
                                "id": tile.id,
                                "error": {"type": type(e).__name__, "message": str(e)},
                            }
                        )

                metadata_data["tiles"] = initial_tiles

                metadata_json = renderer.render({"type": "metadata", "dashboard": metadata_data}).decode()
                yield f"data: {metadata_json}\n\n".encode()

                # Stream remaining tiles (starting from tile 2 if we have more than 2 tiles)
                for order in range(initial_tile_count, len(sorted_tiles)):
                    tile = sorted_tiles[order]
                    try:
                        order_result, tile_data = await database_sync_to_async(
                            serialize_tile_with_context, thread_sensitive=True
                        )(tile, order, context)
                        tile_json = renderer.render({"type": "tile", "order": order, "tile": tile_data}).decode()
                        yield f"data: {tile_json}\n\n".encode()
                    except Exception as e:
                        logger.exception(f"Error serializing tile {tile.id}: {e}")
                        error_json = renderer.render({"type": "error", "tile_id": tile.id, "error": str(e)}).decode()
                        yield f"data: {error_json}\n\n".encode()

                # Send completion signal
                complete_json = renderer.render({"type": "complete"}).decode()
                yield f"data: {complete_json}\n\n".encode()

            except Exception as e:
                logger.exception(f"Error in tile streaming: {e}")
                error_json = renderer.render({"type": "error", "error": str(e)}).decode()
                yield f"data: {error_json}\n\n".encode()

        return sse_streaming_response(
            async_tile_stream_generator()
            if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
            else async_to_sync(lambda: async_tile_stream_generator()),
            endpoint="dashboard_tile_stream",
        )

    def _get_layout_size_from_request(self, request: Request) -> str:
        """Extract layout size parameter from request."""
        layout_size = "sm"

        if request and hasattr(request, "query_params"):
            # Check for both camelCase (from frontend) and snake_case (for compatibility)
            layout_size = request.query_params.get("layoutSize") or request.query_params.get("layout_size") or "sm"
            if layout_size not in ["sm", "xs"]:
                layout_size = "sm"  # fallback to sm if invalid value

        return layout_size

    @extend_schema(request=MoveTileRequestSerializer, responses={200: DashboardSerializer})
    @action(methods=["PATCH", "POST"], detail=True, required_scopes=["dashboard:write"])
    def move_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # TODO could things be rearranged so this is  PATCH call on a resource and not a custom endpoint?
        from_dashboard = self.get_object()
        move_serializer = MoveTileRequestSerializer(data=request.data)
        move_serializer.is_valid(raise_exception=True)
        to_dashboard = move_serializer.validated_data["to_dashboard"]
        tile_id = move_serializer.validated_data["tile"]["id"]

        tile = get_object_or_404(
            DashboardTile.objects.select_related("widget"),
            dashboard_id=from_dashboard.pk,
            id=tile_id,
            dashboard__team__project_id=self.team.project_id,
        )
        to_dashboard_obj = get_object_or_404(Dashboard, id=to_dashboard, team__project_id=self.team.project_id)
        self.check_object_permissions(request, to_dashboard_obj)
        if not self.user_permissions.dashboard(to_dashboard_obj).can_edit:
            raise exceptions.PermissionDenied("You don't have edit permissions for the destination dashboard.")
        if tile.widget_id is not None:
            request_user = cast(User, request.user)
            if not dashboard_widgets_enabled(team=self.team, user=request_user):
                raise exceptions.ValidationError("Dashboard widgets are not enabled for this project.")
            user_access_control = UserAccessControl(user=request_user, team=self.team)
            if tile.widget is None:
                raise exceptions.ValidationError("Widget tile is missing its widget.")
            DashboardSerializer._check_widget_tile_product_access(tile.widget, user_access_control)
        try:
            with transaction.atomic():
                tile.prepare_move_to_dashboard(to_dashboard)
                tile.dashboard_id = to_dashboard
                # Destination is scoped to the current project; align team_id when moving within it.
                tile.team_id = to_dashboard_obj.team_id
                tile.save(update_fields=["dashboard_id", "team_id"])
        except DjangoValidationError:
            logger.exception("validation_error_while_moving_dashboard_tile")
            raise exceptions.ValidationError("Invalid request data for moving tile.")

        serializer = DashboardSerializer(
            from_dashboard,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @extend_schema(request=CopyDashboardTileRequestSerializer, responses={200: DashboardSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["dashboard:write"])
    def copy_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile)."""
        destination = self.get_object()
        if destination.deleted:
            raise exceptions.NotFound()

        serializer = CopyDashboardTileRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from_dashboard_id = serializer.validated_data["fromDashboardId"]
        tile_id = serializer.validated_data["tileId"]

        if from_dashboard_id == destination.pk:
            raise exceptions.ValidationError("Destination must be a different dashboard than the source.")

        source_dashboard = get_object_or_404(Dashboard, id=from_dashboard_id, team__project_id=self.team.project_id)
        user_access_control = UserAccessControl(user=cast(User, request.user), team=self.team)
        if not user_access_control.check_access_level_for_object(source_dashboard, "viewer"):
            raise exceptions.PermissionDenied("You don't have permission to view the source dashboard.")

        tile = get_object_or_404(
            DashboardTile.objects.select_related("widget"),
            dashboard_id=from_dashboard_id,
            id=tile_id,
            dashboard__team__project_id=self.team.project_id,
        )

        if tile.widget_id is not None:
            if not dashboard_widgets_enabled(team=self.team, user=cast(User, request.user)):
                raise exceptions.ValidationError("Dashboard widgets are not enabled for this project.")
            if tile.widget is None:
                raise exceptions.ValidationError("Widget tile is missing its widget.")
            DashboardSerializer._check_widget_tile_product_access(tile.widget, user_access_control)
            try:
                with transaction.atomic():
                    DashboardSerializer._clone_widget_tile_to_dashboard(tile, destination, cast(User, request.user))
            except DjangoValidationError:
                logger.warning("validation_error_while_copying_dashboard_tile", exc_info=True)
                raise exceptions.ValidationError("Unable to copy tile due to invalid data.")
            return Response(
                DashboardSerializer(
                    get_object_or_404(Dashboard, id=destination.pk, team__project_id=self.team.project_id),
                    context=self.get_serializer_context(),
                ).data
            )

        if tile.insight is None and tile.text is None:
            raise exceptions.ValidationError("Only insight, text, and widget tiles can be copied between dashboards.")

        if tile.insight is not None:
            if not user_access_control.check_access_level_for_object(tile.insight, "viewer"):
                raise exceptions.PermissionDenied("You don't have permission to view this insight.")

            if DashboardTile.objects.filter(dashboard=destination, insight=tile.insight).exists():
                raise exceptions.ValidationError("This insight is already on the destination dashboard.")
        elif tile.text is not None:
            if DashboardTile.objects.filter(dashboard=destination, text=tile.text).exists():
                raise exceptions.ValidationError("This text card is already on the destination dashboard.")

        try:
            with transaction.atomic():
                tile.copy_to_dashboard(destination)
        except DjangoValidationError:
            logger.warning("validation_error_while_copying_dashboard_tile", exc_info=True)
            raise exceptions.ValidationError("Unable to copy tile due to invalid data.")
        except IntegrityError:
            raise exceptions.ValidationError(
                "This insight is already on the destination dashboard."
                if tile.insight is not None
                else "This text card is already on the destination dashboard."
            )

        return Response(
            DashboardSerializer(
                get_object_or_404(Dashboard, id=destination.pk, team__project_id=self.team.project_id),
                context=self.get_serializer_context(),
            ).data
        )

    @extend_schema(request=ReorderTilesRequestSerializer, responses={200: DashboardSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["dashboard:write"])
    def reorder_tiles(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()
        serializer = ReorderTilesRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tile_order: list[int] = serializer.validated_data["tile_order"]
        layout_mode = ReorderLayout(serializer.validated_data["layout"])

        if len(tile_order) != len(set(tile_order)):
            return Response(
                {"detail": "tile_order must contain unique tile IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tiles = DashboardTile.objects.filter(dashboard=dashboard, id__in=tile_order)
        tile_map = {tile.id: tile for tile in tiles}

        missing = set(tile_order) - set(tile_map.keys())
        if missing:
            return Response(
                {"detail": f"Tile IDs not found on this dashboard: {sorted(missing)}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        _apply_reorder_layout(tile_order, tile_map, layout_mode)

        DashboardTile.objects.bulk_update(tile_map.values(), ["layouts"])

        return Response(DashboardSerializer(dashboard, context=self.get_serializer_context()).data)

    @extend_schema(
        request=CreateTextTileRequestSerializer,
        responses={201: DashboardTileSerializer},
    )
    @action(methods=["POST"], detail=True, required_scopes=["dashboard:write"])
    def create_text_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Add a markdown text tile to a dashboard.

        Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
        or annotations between insight tiles to give the dashboard structure.
        """
        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()
        if not self.user_permissions.dashboard(dashboard).can_edit:
            raise exceptions.PermissionDenied("You don't have edit permissions for this dashboard.")

        serializer = CreateTextTileRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        user = cast(User, request.user)
        with transaction.atomic():
            text = Text.objects.create(
                body=validated["body"],
                team=dashboard.team,
                created_by=user,
                last_modified_at=now(),
            )
            tile_data: dict[str, Any] = {}
            if "layouts" in validated:
                tile_data["layouts"] = validated["layouts"]
            if "color" in validated:
                tile_data["color"] = validated["color"]
            tile, _ = DashboardSerializer._upsert_tile(dashboard, tile_data, text=text)

        return Response(
            DashboardTileSerializer(tile, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=UpdateTextTileRequestSerializer,
        responses={200: DashboardTileSerializer},
    )
    @action(methods=["POST"], detail=True, required_scopes=["dashboard:write"])
    def update_text_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the markdown body, layout, or color of an existing text tile on a dashboard."""
        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()
        if not self.user_permissions.dashboard(dashboard).can_edit:
            raise exceptions.PermissionDenied("You don't have edit permissions for this dashboard.")

        serializer = UpdateTextTileRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        tile = get_object_or_404(
            DashboardTile,
            id=validated["tile_id"],
            dashboard=dashboard,
            dashboard__team__project_id=self.team.project_id,
        )
        if tile.text is None:
            raise exceptions.ValidationError("Tile is not a text tile.")

        user = cast(User, request.user)
        with transaction.atomic():
            text = tile.text
            if "body" in validated:
                text.body = validated["body"]
            text.last_modified_by = user
            text.last_modified_at = now()
            text.save()

            tile_updates: list[str] = []
            if "layouts" in validated:
                tile.layouts = validated["layouts"]
                tile_updates.append("layouts")
            if "color" in validated:
                tile.color = validated["color"]
                tile_updates.append("color")
            if tile_updates:
                tile.save(update_fields=tile_updates)

        tile.refresh_from_db()
        return Response(DashboardTileSerializer(tile, context=self.get_serializer_context()).data)

    @extend_schema(
        operation_id="dashboards_delete_tile",
        request=DeleteTileRequestSerializer,
        responses={204: None},
    )
    @action(methods=["POST"], detail=True, required_scopes=["dashboard:write"])
    def delete_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Soft-delete a single tile from a dashboard.

        Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
        object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
        use the dashboard delete endpoint instead.
        """
        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()
        if not self.user_permissions.dashboard(dashboard).can_edit:
            raise exceptions.PermissionDenied("You don't have edit permissions for this dashboard.")

        serializer = DeleteTileRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tile_id = serializer.validated_data["tile_id"]

        tile = get_object_or_404(
            DashboardTile,
            id=tile_id,
            dashboard=dashboard,
            dashboard__team__project_id=self.team.project_id,
        )
        # Collapse the vertical gap the removed tile leaves, matching the dashboard UI
        # (react-grid-layout compacts upward on render but never persists it).
        with transaction.atomic():
            tile.deleted = True
            tile.save(update_fields=["deleted"])

            remaining = list(DashboardTile.objects.filter(dashboard=dashboard))
            changed_ids = _compact_tile_layouts(remaining)
            if changed_ids:
                DashboardTile.objects.bulk_update(
                    [remaining_tile for remaining_tile in remaining if remaining_tile.id in changed_ids],
                    ["layouts"],
                )

        _report_dashboard_tile_removed(
            user=cast(User, request.user),
            dashboard=dashboard,
            tile=tile,
            request=request,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "refresh",
                OpenApiTypes.STR,
                enum=["force_cache", "blocking", "force_blocking"],
                description=(
                    "Cache behavior. 'force_cache' (default) serves from cache even if stale. "
                    "'blocking' uses cache if fresh, otherwise recalculates. "
                    "'force_blocking' always recalculates."
                ),
            ),
            OpenApiParameter(
                "output_format",
                OpenApiTypes.STR,
                enum=["optimized", "json"],
                description=(
                    "'optimized' (default) returns LLM-friendly formatted text per insight. "
                    "'json' returns the raw query result objects."
                ),
            ),
            VARIABLES_OVERRIDE_PARAM,
            FILTERS_OVERRIDE_PARAM,
        ],
        responses={200: RunInsightsResponseSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["query:read"])
    def run_insights(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Run all insights on a dashboard and return their results."""
        dashboard = self.get_object()
        output_format = request.query_params.get("output_format", "optimized")

        context = self.get_serializer_context()
        context["dashboard"] = dashboard

        tiles = DashboardTile.dashboard_queryset(dashboard.tiles.all()).prefetch_related(
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            ),
        )
        self.user_permissions.set_preloaded_dashboard_tiles(list(tiles))

        sorted_tiles = DashboardTile.sort_tiles_by_layout(tiles, "sm")

        tile_results = []
        for order, tile in enumerate(sorted_tiles):
            if not tile.insight or not tile.insight.query:
                continue
            tile_context = {**context, "dashboard_tile": tile, "order": order}
            tile_data = DashboardTileResultSerializer(tile, context=tile_context).data

            if output_format == "optimized":
                insight_data = tile_data.get("insight") or {}
                formatted = self._format_insight_for_llm(tile.insight, insight_data)
                if formatted is not None and insight_data:
                    insight_data["result"] = formatted

            tile_results.append(tile_data)

        return Response({"results": tile_results})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="tile_ids",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Comma-separated dashboard tile IDs to run widgets for.",
            ),
        ],
        responses={200: RunWidgetsResponseSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["dashboard:read"])
    def run_widgets(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not dashboard_widgets_enabled(team=self.team, user=cast(User, request.user)):
            raise exceptions.PermissionDenied("Dashboard widgets are not enabled for this project.")

        tile_ids_param = request.query_params.get("tile_ids")
        if not tile_ids_param:
            raise exceptions.ValidationError("tile_ids is required.")

        try:
            tile_ids = [int(tile_id.strip()) for tile_id in tile_ids_param.split(",") if tile_id.strip()]
        except ValueError as exc:
            raise exceptions.ValidationError("tile_ids must be a comma-separated list of integers.") from exc

        tile_ids = list(dict.fromkeys(tile_ids))
        if not tile_ids:
            raise exceptions.ValidationError("tile_ids must include at least one tile ID.")
        if len(tile_ids) > MAX_WIDGETS_BATCH_SIZE:
            raise exceptions.ValidationError(f"At most {MAX_WIDGETS_BATCH_SIZE} tile_ids may be requested at once.")

        dashboard = self.get_object()
        user_access_control = UserAccessControl(user=cast(User, request.user), team=self.team)
        distinct_id = str(cast(User, request.user).distinct_id)

        tiles_by_id = {
            tile.id: tile
            for tile in DashboardTile.objects.select_related("widget").filter(
                dashboard=dashboard, id__in=tile_ids, widget__isnull=False
            )
        }

        results_by_id: dict[int, dict[str, Any]] = {}
        query_work_items: list[_RunWidgetQueryWorkItem] = []

        for tile_id in tile_ids:
            tile = tiles_by_id.get(tile_id)
            if tile is None or tile.widget is None:
                results_by_id[tile_id] = {
                    "tile_id": tile_id,
                    "widget_type": None,
                    "result": None,
                    "error": "Tile not found or is not a widget tile.",
                }
                continue

            widget = tile.widget
            registry_entry = get_widget_registry_entry(widget.widget_type)
            if registry_entry is None:
                results_by_id[tile_id] = {
                    "tile_id": tile_id,
                    "widget_type": widget.widget_type,
                    "result": None,
                    "error": f"Unknown widget type: {widget.widget_type}",
                }
                continue

            access_error = get_widget_product_access_error(registry_entry, user_access_control)
            if access_error:
                results_by_id[tile_id] = {
                    "tile_id": tile_id,
                    "widget_type": widget.widget_type,
                    "result": None,
                    "error": access_error,
                }
                continue

            scope_error = get_widget_api_scope_error(registry_entry, request)
            if scope_error:
                results_by_id[tile_id] = {
                    "tile_id": tile_id,
                    "widget_type": widget.widget_type,
                    "result": None,
                    "error": scope_error,
                }
                continue

            widget_throttle_error = get_dashboard_widget_query_throttle_error(request, self)
            if widget_throttle_error:
                results_by_id[tile_id] = {
                    "tile_id": tile_id,
                    "widget_type": widget.widget_type,
                    "result": None,
                    "error": widget_throttle_error,
                }
                continue

            if widget.widget_type == SESSION_REPLAY_LIST_WIDGET_TYPE:
                replay_throttle_error = get_replay_listing_throttle_error(request, self)
                if replay_throttle_error:
                    results_by_id[tile_id] = {
                        "tile_id": tile_id,
                        "widget_type": widget.widget_type,
                        "result": None,
                        "error": replay_throttle_error,
                    }
                    continue

            query_work_items.append(
                {
                    "tile_id": tile_id,
                    "widget_type": widget.widget_type,
                    "query_fn": registry_entry["query_fn"],
                    "config": widget.config,
                    "user": cast(User, request.user),
                }
            )

        if query_work_items:
            max_workers = min(RUN_WIDGETS_QUERY_CONCURRENCY, len(query_work_items))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _run_widget_query,
                        self.team,
                        work_item,
                        dashboard_id=dashboard.id,
                        distinct_id=distinct_id,
                    ): work_item["tile_id"]
                    for work_item in query_work_items
                }
                for future in as_completed(futures):
                    tile_id = futures[future]
                    results_by_id[tile_id] = future.result()

        results = [results_by_id[tile_id] for tile_id in tile_ids]

        return Response({"results": results})

    @extend_schema(responses={200: WidgetCatalogResponseSerializer})
    @action(methods=["GET"], detail=False, required_scopes=["dashboard:read"])
    def widget_catalog(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List registered dashboard widget types and per-type config_schema documentation for agents."""
        return Response({"results": get_widget_catalog_entries()})

    @extend_schema(
        request=AddDashboardWidgetsBatchRequestOpenApiSerializer,
        responses={201: AddDashboardWidgetsBatchResponseSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="widgets/batch", required_scopes=["dashboard:write"])
    def widgets_batch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Add multiple widget tiles to a dashboard in one atomic request."""
        if not dashboard_widgets_enabled(team=self.team, user=cast(User, request.user)):
            raise exceptions.ValidationError("Dashboard widgets are not enabled for this project.")

        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()

        serializer = AddDashboardWidgetsBatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        widget_payloads = cast(builtins.list[dict[str, Any]], serializer.validated_data["widgets"])

        user = cast(User, request.user)
        user_access_control = UserAccessControl(user=user, team=self.team)
        tile_context = {**self.get_serializer_context(), "dashboard": dashboard}

        with transaction.atomic():
            existing_sm_layouts = collect_dashboard_sm_layouts_for_dashboard(dashboard)
            pending_sm_layouts: builtins.list[dict[str, Any]] = []
            tiles: builtins.list[DashboardTile] = []

            for payload in widget_payloads:
                tile = self._create_widget_tile_from_payload(
                    dashboard=dashboard,
                    user=user,
                    user_access_control=user_access_control,
                    payload=payload,
                    existing_sm_layouts=existing_sm_layouts,
                    pending_sm_layouts=pending_sm_layouts,
                )
                tiles.append(tile)
                sm_layout = tile.layouts.get("sm") if isinstance(tile.layouts, dict) else None
                if isinstance(sm_layout, dict):
                    pending_sm_layouts.append(sm_layout)

        for tile in tiles:
            assert tile.widget is not None
            _report_dashboard_tile_added(
                user=user,
                dashboard=dashboard,
                tile_type="widget",
                widget_type=tile.widget.widget_type,
                request=request,
                tile=tile,
            )

        return Response(
            {"tiles": DashboardTileSerializer(tiles, context=tile_context, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    def _create_widget_tile_from_payload(
        self,
        *,
        dashboard: Dashboard,
        user: User,
        user_access_control: UserAccessControl,
        payload: dict[str, Any],
        existing_sm_layouts: builtins.list[dict[str, Any]] | None = None,
        pending_sm_layouts: builtins.list[dict[str, Any]] | None = None,
    ) -> DashboardTile:
        widget_type = payload["widget_type"]
        config = payload["config"]
        normalized_widget_type, validated_config = prepare_widget_tile_create(
            team=self.team,
            widget_type=widget_type,
            config=config,
            user=user,
            user_access_control=user_access_control,
        )
        _check_dashboard_widget_count_limit(dashboard=dashboard, user=user)
        layouts = payload.get("layouts")
        if layouts is None:
            layouts = stack_widget_layout_at_bottom(
                widget_type=normalized_widget_type,
                existing_sm_layouts=existing_sm_layouts or [],
                pending_sm_layouts=pending_sm_layouts,
            )
        tile_defaults: dict[str, Any] = {
            "layouts": layouts,
        }
        if "show_description" in payload:
            tile_defaults["show_description"] = payload["show_description"]

        widget = DashboardWidget.objects.create(
            team_id=self.team_id,
            widget_type=normalized_widget_type,
            name=payload.get("name") or None,
            description=payload.get("description", ""),
            config=validated_config,
            created_by=user,
            last_modified_by=user,
        )
        return DashboardTile.objects.create(
            dashboard=dashboard,
            team_id=dashboard.team_id,
            widget=widget,
            **tile_defaults,
        )

    @extend_schema(
        operation_id="dashboards_update_widgets_batch",
        request=UpdateDashboardWidgetsBatchRequestOpenApiSerializer,
        responses={200: UpdateDashboardWidgetsBatchResponseSerializer},
    )
    @action(methods=["PATCH"], detail=True, url_path="widgets/batch_update", required_scopes=["dashboard:write"])
    def update_widgets_batch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the settings of existing widgets in place, atomically — config, name, and description.

        Each entry targets a widget by its tile_id and reuses the same write path as the dashboard PATCH endpoint.
        The widget_type is immutable. This edits widget settings only (config, name, description); tile placement
        (layouts, show_description) is a dashboard concern — use the dashboard PATCH endpoint or reorder_tiles for
        that. All updates succeed or fail together. To add new widgets, use the widgets/batch POST endpoint; to
        remove one, use delete_tile.
        """
        if not dashboard_widgets_enabled(team=self.team, user=cast(User, request.user)):
            raise exceptions.ValidationError("Dashboard widgets are not enabled for this project.")

        dashboard = self.get_object()
        if dashboard.deleted:
            raise exceptions.NotFound()
        if not self.user_permissions.dashboard(dashboard).can_edit:
            raise exceptions.PermissionDenied("You don't have edit permissions for this dashboard.")

        serializer = UpdateDashboardWidgetsBatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        widget_payloads = cast(builtins.list[dict[str, Any]], serializer.validated_data["widgets"])

        user = cast(User, request.user)
        user_access_control = UserAccessControl(user=user, team=self.team)

        with transaction.atomic():
            tiles = [
                self._apply_widget_tile_update(
                    dashboard=dashboard,
                    user=user,
                    user_access_control=user_access_control,
                    payload=payload,
                    request=request,
                )
                for payload in widget_payloads
            ]

        for tile in tiles:
            tile.refresh_from_db()

        # Report after the transaction commits so a rolled-back batch never emits events.
        for tile, payload in zip(tiles, widget_payloads):
            _report_dashboard_widget_updated(
                user=user,
                dashboard=dashboard,
                tile=tile,
                fields_changed=[field for field in ("config", "name", "description") if field in payload],
                request=request,
            )

        tile_context = {**self.get_serializer_context(), "dashboard": dashboard}
        return Response({"tiles": DashboardTileSerializer(tiles, context=tile_context, many=True).data})

    def _apply_widget_tile_update(
        self,
        *,
        dashboard: Dashboard,
        user: User,
        user_access_control: UserAccessControl,
        payload: dict[str, Any],
        request: Request,
    ) -> DashboardTile:
        tile = get_object_or_404(
            DashboardTile,
            id=payload["tile_id"],
            dashboard=dashboard,
            dashboard__team__project_id=self.team.project_id,
        )
        if tile.widget is None:
            raise exceptions.ValidationError(f"Tile {payload['tile_id']} is not a widget tile.")

        widget_data: dict[str, Any] = {
            field: payload[field] for field in ("widget_type", "config", "name", "description") if field in payload
        }
        if widget_data:
            DashboardSerializer._apply_patch_widget_update(
                widget=tile.widget,
                widget_data=widget_data,
                user=user,
                user_access_control=user_access_control,
                dashboard=dashboard,
                request=request,
            )

        return tile

    def _format_insight_for_llm(self, insight: Insight, insight_data: dict) -> str | None:
        if not settings.EE_AVAILABLE:
            return None
        try:
            from ee.hogai.context.insight.format import format_query_results_for_llm

            query_dict = insight.query
            if not query_dict:
                return None
            query = InsightVizNode.model_validate(query_dict)
            if not query.source:
                return None
            result_dict = {"results": insight_data.get("result"), "columns": insight_data.get("columns")}
            return format_query_results_for_llm(query.source, result_dict, self.team)
        except Exception:
            logger.warning("dashboard_run_insights_format_failed", exc_info=True, insight_id=insight.id)
            return None

    @action(
        methods=["POST"],
        detail=False,
        parser_classes=[DashboardTemplateCreationJSONSchemaParser],
    )
    def create_from_template_json(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = Dashboard.objects.create(
            team_id=self.team_id,
            created_by=cast(User, request.user),
            _create_in_folder=request.data.get("_create_in_folder"),  # type: ignore
        )

        try:
            dashboard_template = dashboard_template_from_creation_payload(request.data["template"])
            creation_context = request.data.get("creation_context")
            create_from_template(
                dashboard,
                dashboard_template,
                cast(User, request.user),
                user_access_control=UserAccessControl(user=cast(User, request.user), team=self.team),
            )

            template_body = request.data["template"]
            raw_scope = template_body.get("scope")
            if raw_scope is None or raw_scope == "":
                template_scope_props: dict[str, str | None] = {"template_scope": None}
            else:
                template_scope_props = {"template_scope": raw_scope if isinstance(raw_scope, str) else str(raw_scope)}

            report_user_action(
                request.user,
                "dashboard created",
                {
                    **dashboard.get_analytics_metadata(),
                    "from_template": True,
                    "template_key": dashboard_template.template_name,
                    **template_scope_props,
                    "duplicated": False,
                    "creation_context": creation_context,
                },
                team=dashboard.team,
                request=request,
            )
        except Exception:
            dashboard.delete()
            raise

        return Response(DashboardSerializer(dashboard, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=False)
    def create_unlisted_dashboard(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Creates an unlisted dashboard from template by tag.
        Enforces uniqueness (one per tag per team).
        Returns 409 if unlisted dashboard with this tag already exists.
        """
        from django.db import transaction

        from posthog.models.team import Team

        tag = request.data.get("tag")

        if not tag:
            return Response(
                {"error": "tag is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if tag not in self.TEMPLATE_MAP:
            return Response(
                {"error": f"Unknown template tag: {tag}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            Team.objects.select_for_update().filter(id=self.team_id).first()

            existing = Dashboard.objects.filter(
                team=self.team,
                deleted=False,
                creation_mode="unlisted",
                tagged_items__tag__name=tag,
            ).first()

            if existing:
                return Response(
                    {"error": f"Unlisted dashboard with tag '{tag}' already exists"},
                    status=status.HTTP_409_CONFLICT,
                )

            template = self.TEMPLATE_MAP[tag]()
            dashboard = Dashboard.objects.create(
                team_id=self.team_id,
                name=template.template_name,
                description=template.dashboard_description or "",
                filters={**(template.dashboard_filters or {}), "__template_version": 1},
                created_by=cast(User, request.user),
                creation_mode="unlisted",
            )

            create_from_template(
                dashboard,
                template,
                cast(User, request.user),
                user_access_control=UserAccessControl(user=cast(User, request.user), team=self.team),
            )

            return Response(
                DashboardSerializer(dashboard, context=self.get_serializer_context()).data,
                status=status.HTTP_201_CREATED,
            )


class LegacyDashboardsViewSet(DashboardsViewSet):
    param_derived_from_user_current_team = "project_id"

    def get_parents_query_dict(self) -> dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team__project_id": self.project_id}


class LegacyInsightViewSet(InsightViewSet):
    param_derived_from_user_current_team = "project_id"
