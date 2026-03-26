from typing import Any, Literal, TypedDict, cast

from django.db import transaction

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DataTableNode, HogQLQuery, InsightVizNode, QuerySchemaRoot

from posthog.event_usage import EventSource, report_user_action
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.sync import database_sync_to_async
from posthog.utils import pluralize

from ee.hogai.artifacts.types import ModelArtifactResult, VisualizationWithSourceResult
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.upsert_dashboard.prompts import (
    CREATE_NO_INSIGHTS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    MISSING_INSIGHT_IDS_PROMPT,
    PERMISSION_REQUEST_PROMPT,
    UPDATE_NO_CHANGES_PROMPT,
    UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE,
    UPSERT_DASHBOARD_TOOL_PROMPT,
)
from ee.hogai.utils.prompt import format_prompt_string

logger = structlog.get_logger(__name__)


class CreateDashboardToolArgs(BaseModel):
    """Schema to create a new dashboard with provided insights."""

    action: Literal["create"] = "create"
    insight_ids: list[str] = Field(
        description="The IDs of the insights to be included in the dashboard. It might be a mix of existing and new insights."
    )
    name: str = Field(
        description="A short and concise (3-7 words) name of the dashboard. It will be displayed as a header in the dashboard tile."
    )
    description: str = Field(description="A short and concise description of the dashboard.")


class UpdateDashboardToolArgs(BaseModel):
    """Schema to update an existing dashboard with provided insights."""

    action: Literal["update"] = "update"
    dashboard_id: str = Field(description="Provide the ID of the dashboard to be update it.")
    insight_ids: list[str] | None = Field(
        description="The IDs of the insights for the dashboard. Replaces all existing insights.",
        default=None,
    )
    layout_mode: Literal["preserve_existing", "reflow_all"] = Field(
        description="How to handle existing tile layouts when insight_ids are provided. Use preserve_existing by default. Use reflow_all only when the user explicitly asks to rearrange or reorder tiles.",
        default="preserve_existing",
    )
    name: str | None = Field(
        description="A short and concise (3-7 words) name of the dashboard. If not provided, the dashboard name will not be updated.",
        default=None,
    )
    description: str | None = Field(
        description="A short and concise description of the dashboard. If not provided, the dashboard description will not be updated.",
        default=None,
    )


UpsertDashboardAction = CreateDashboardToolArgs | UpdateDashboardToolArgs


class UpsertDashboardToolArgs(BaseModel):
    action: UpsertDashboardAction = Field(
        description="The action to perform. Either create a new dashboard or update an existing one.",
        discriminator="action",
    )


class UpdateDiff(TypedDict):
    created: list[VisualizationWithSourceResult]
    deleted: list[DashboardTile]


class ReflowRowItem(TypedDict):
    tile: DashboardTile
    h: int
    w: int


class ReflowTileLayoutUpdate(TypedDict):
    tile: DashboardTile
    layouts: dict[str, dict[str, int]]


class UpsertDashboardTool(MaxTool):
    name: Literal["upsert_dashboard"] = "upsert_dashboard"
    description: str = UPSERT_DASHBOARD_TOOL_PROMPT
    context_prompt_template: str = UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE
    args_schema: type[BaseModel] = UpsertDashboardToolArgs
    _cached_update_diff: UpdateDiff | None = None

    def get_required_resource_access(self):
        return [("dashboard", "editor")]

    async def is_dangerous_operation(self, *, action: UpsertDashboardAction, **kwargs) -> bool:
        """Update operations that delete existing insights are dangerous."""
        if isinstance(action, UpdateDashboardToolArgs) and action.insight_ids:
            dashboard = await self._get_dashboard(action.dashboard_id)
            sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
            diff = await self._get_update_diff(sorted_tiles, action.insight_ids)
            return len(diff["deleted"]) > 0
        return False

    async def format_dangerous_operation_preview(self, *, action: UpsertDashboardAction, **kwargs) -> str:
        """
        Build a rich preview showing dashboard details and what will be modified.
        """
        if isinstance(action, CreateDashboardToolArgs):
            raise MaxToolFatalError("Create dashboard operation is not dangerous.")

        dashboard = await self._get_dashboard(action.dashboard_id)
        sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
        diff = await self._get_update_diff(sorted_tiles, action.insight_ids or [])

        def get_insight_name(insight: Insight) -> str:
            return insight.name or insight.derived_name or f"Insight #{insight.short_id or insight.id}"

        def get_artifact_name(artifact: VisualizationWithSourceResult) -> str:
            return artifact.content.name or "Insight"

        def join(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items)

        created_list = [get_artifact_name(artifact) for artifact in diff["created"]]
        deleted_list = [get_insight_name(tile.insight) for tile in diff["deleted"] if tile.insight is not None]

        return format_prompt_string(
            PERMISSION_REQUEST_PROMPT,
            dashboard_name=dashboard.name or f"Dashboard #{dashboard.id}",
            new_dashboard_name=action.name,
            new_dashboard_description=action.description,
            deleted_insights=join(deleted_list),
            deleted_count=pluralize(len(deleted_list), "insight"),
            new_insights=join(created_list),
            added_count=pluralize(len(created_list), "insight"),
        )

    async def _arun_impl(self, action: UpsertDashboardAction) -> tuple[str, dict | None]:
        if isinstance(action, CreateDashboardToolArgs):
            return await self._handle_create(action)
        else:
            return await self._handle_update(action)

    async def _handle_create(self, action: CreateDashboardToolArgs) -> tuple[str, dict | None]:
        """Handle CREATE action: create a new dashboard with insights."""
        artifacts = await self._context_manager.artifacts.aget_visualizations(self._state.messages, action.insight_ids)

        missing_ids = [insight_id for insight_id, artifact in zip(action.insight_ids, artifacts) if artifact is None]
        if missing_ids:
            raise MaxToolRetryableError(format_prompt_string(MISSING_INSIGHT_IDS_PROMPT, missing_ids=missing_ids))

        validated_artifacts = cast(list[VisualizationWithSourceResult], artifacts)
        insights = self._resolve_insights(validated_artifacts)

        if not insights:
            return CREATE_NO_INSIGHTS_PROMPT, None

        dashboard = await self._create_dashboard_with_tiles(action.name, action.description, insights)
        await self._report_dashboard_action(dashboard, "dashboard created")
        await self._report_new_insights(validated_artifacts, insights)
        output = await self._format_dashboard_output(dashboard, insights)

        return output, {"dashboard_id": dashboard.id}

    async def _handle_update(self, action: UpdateDashboardToolArgs) -> tuple[str, dict | None]:
        """Handle UPDATE action: update an existing dashboard."""
        dashboard = await self._get_dashboard(action.dashboard_id)
        has_changes = action.insight_ids or action.name is not None or action.description is not None
        if not has_changes:
            return UPDATE_NO_CHANGES_PROMPT, None

        insight_ids = action.insight_ids or []
        artifacts = await self._get_visualization_artifacts(insight_ids) if insight_ids else []

        dashboard, resolved_insights = await self._update_dashboard_with_tiles(
            dashboard,
            action.name,
            action.description,
            insight_ids,
            artifacts,
            action.layout_mode,
        )
        await self._report_dashboard_action(dashboard, "dashboard updated")

        if artifacts:
            await self._report_new_insights(cast(list[VisualizationWithSourceResult], artifacts), resolved_insights)

        # Re-fetch sorted tiles to get the latest state
        sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
        insights = [tile.insight for tile in sorted_tiles if tile.insight is not None]

        output = await self._format_dashboard_output(dashboard, insights)

        return output, {"dashboard_id": dashboard.id}

    def _resolve_insights(self, artifacts: list[VisualizationWithSourceResult]) -> list[Insight]:
        """
        Resolve insight_ids using VisualizationHandler.
        Returns (resolved_insights, missing_ids) in same order as input.

        For State/Artifact sources, creates and saves new Insights before adding to dashboard.
        """
        resolved: list[Insight] = []

        for result in artifacts:
            if isinstance(result, ModelArtifactResult):
                resolved.append(result.model)
            else:
                # State or Artifact source - need to create and save insight from artifact content
                content = result.content
                # Coerce query to the QuerySchema union
                coerced_query = QuerySchemaRoot.model_validate(content.query.model_dump(mode="json")).root
                if isinstance(coerced_query, HogQLQuery):
                    converted = DataTableNode(source=coerced_query).model_dump(exclude_none=True)
                else:
                    converted = InsightVizNode(source=coerced_query).model_dump(exclude_none=True)

                insight = Insight(
                    team=self._team,
                    created_by=self._user,
                    name=(content.name or "Untitled")[:400],
                    description=(content.description or "")[:400],
                    query=converted,
                    saved=True,
                )
                resolved.append(insight)

        return resolved

    async def _report_dashboard_action(self, dashboard: Dashboard, event: str) -> None:
        await database_sync_to_async(report_user_action)(
            self._user,
            event,
            {
                **await database_sync_to_async(dashboard.get_analytics_metadata)(),
                "source": EventSource.POSTHOG_AI,
            },
            team=self._team,
        )

    async def _report_new_insights(
        self, artifacts: list[VisualizationWithSourceResult], insights: list[Insight]
    ) -> None:
        for artifact, insight in zip(artifacts, insights):
            if not isinstance(artifact, ModelArtifactResult):
                await database_sync_to_async(report_user_action)(
                    self._user,
                    "insight created",
                    {
                        "insight_id": insight.short_id,
                        "source": EventSource.POSTHOG_AI,
                    },
                    team=self._team,
                )

    def _create_resolved_insights(self, results: list[Insight]) -> list[Insight]:
        """
        Create insights that are not yet saved.
        """
        for insight in results:
            if getattr(insight, "pk", None):
                continue
            insight.save()
        return results

    @database_sync_to_async
    @transaction.atomic
    def _create_dashboard_with_tiles(self, name: str, description: str, insights: list[Insight]) -> Dashboard:
        """Create a new dashboard with tiles for the given insights."""
        dashboard = Dashboard.objects.create(
            name=name,
            description=description,
            team=self._team,
            created_by=self._user,
        )
        insights = self._create_resolved_insights(insights)
        DashboardTile.objects.bulk_create(
            [DashboardTile(dashboard=dashboard, insight=insight, layouts={}) for insight in insights]
        )
        return dashboard

    @database_sync_to_async
    @transaction.atomic
    def _update_dashboard_with_tiles(
        self,
        dashboard: Dashboard,
        name: str | None,
        description: str | None,
        insight_ids: list[str],
        artifacts: list[VisualizationWithSourceResult],
        layout_mode: Literal["preserve_existing", "reflow_all"],
    ) -> tuple[Dashboard, list[Insight]]:
        """Update dashboard tiles based on provided insight IDs.

        Args:
            dashboard: The dashboard to update
            name: New dashboard name (if provided)
            description: New dashboard description (if provided)
            insight_ids: Ordered list of insight IDs for the dashboard
            artifacts: Resolved visualization artifacts matching insight_ids order
            layout_mode: Layout strategy for existing tiles

        Returns:
            Tuple of (dashboard, resolved_insights) where resolved_insights
            corresponds 1:1 with artifacts in the same order.
        """
        if name is not None:
            dashboard.name = name
        if description is not None:
            dashboard.description = description
        if name is not None or description is not None:
            dashboard.save(update_fields=["name", "description"])

        if not insight_ids:
            return dashboard, []

        # 1. Get all existing tiles including soft deleted
        all_tiles = list(
            DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard).select_related("insight")
        )

        # Build lookup: short_id -> tile (for matching by artifact ID)
        short_id_to_tile: dict[str, DashboardTile] = {}
        for tile in all_tiles:
            if tile.insight and tile.insight.short_id:
                short_id_to_tile[tile.insight.short_id] = tile

        # Resolve artifacts to insights
        resolved_insights = self._create_resolved_insights(self._resolve_insights(artifacts))

        # Track tiles that will be active after update
        active_tile_ids: set[int] = set()
        tiles_to_update: list[DashboardTile] = []
        restored_tile_ids: list[int] = []

        # 2. Create new tiles or restore soft deleted
        for insight_id, insight in zip(insight_ids, resolved_insights):
            existing_tile = short_id_to_tile.get(insight_id)

            if existing_tile:
                # Restore if soft deleted
                if existing_tile.deleted:
                    existing_tile.deleted = False
                    restored_tile_ids.append(existing_tile.id)
                active_tile_ids.add(existing_tile.id)
                tiles_to_update.append(existing_tile)
            else:
                # Create new tile
                new_tile = DashboardTile.objects.create(
                    dashboard=dashboard,
                    insight=insight,
                    layouts={},
                )
                active_tile_ids.add(new_tile.id)
                tiles_to_update.append(new_tile)

        # 3. Soft delete insight tiles not in the new list (preserve text tiles)
        tiles_to_delete = [
            t.id for t in all_tiles if t.id not in active_tile_ids and not t.deleted and t.insight_id is not None
        ]
        if tiles_to_delete:
            # nosemgrep: idor-lookup-without-team
            DashboardTile.objects.filter(id__in=tiles_to_delete).update(deleted=True)

        if layout_mode == "preserve_existing":
            if restored_tile_ids:
                DashboardTile.objects_including_soft_deleted.filter(id__in=restored_tile_ids).update(deleted=False)
            return dashboard, resolved_insights

        fixed_non_insight_vertical_spans: list[tuple[int, int]] = []
        for tile in all_tiles:
            if tile.deleted or tile.insight_id is not None:
                continue
            sm_layout = (tile.layouts or {}).get("sm", {})
            raw_y = sm_layout.get("y")
            raw_h = sm_layout.get("h")
            if not isinstance(raw_y, int | float) or not isinstance(raw_h, int | float):
                continue
            y_start = int(raw_y)
            height = int(raw_h)
            if y_start < 0 or height <= 0:
                continue
            fixed_non_insight_vertical_spans.append((y_start, y_start + height))

        # 4. Reflow insight tile layouts when requested.
        layout_updates = self._compute_reflow_layout_updates(tiles_to_update, fixed_non_insight_vertical_spans)
        for layout_update in layout_updates:
            row_tile = layout_update["tile"]
            row_tile.layouts = layout_update["layouts"]
            row_tile.save(update_fields=["layouts", "deleted"])

        return dashboard, resolved_insights

    @staticmethod
    def _compute_reflow_layout_updates(
        tiles_to_update: list[DashboardTile], fixed_non_insight_vertical_spans: list[tuple[int, int]]
    ) -> list[ReflowTileLayoutUpdate]:
        # Reflow is intentionally row-based and simple:
        # - preserve tile order
        # - normalize row heights
        # - fill row gaps using equal widths
        # - allow local adaptation for inserted middle tiles
        # - avoid vertical overlap with fixed non-insight tiles (e.g. text)
        column_count = 12
        xs_y = 0  # For xs breakpoint (single column)
        rows: list[list[ReflowRowItem]] = []
        current_row: list[ReflowRowItem] = []
        current_row_width = 0

        for tile in tiles_to_update:
            sm_layout = (tile.layouts or {}).get("sm", {})

            # Use original sizes as the baseline, falling back to defaults.
            raw_h = sm_layout.get("h")
            raw_w = sm_layout.get("w")

            h = int(raw_h) if isinstance(raw_h, int | float) and raw_h > 0 else 5
            w = int(raw_w) if isinstance(raw_w, int | float) and raw_w > 0 else 6
            w = min(w, column_count)

            if current_row and current_row_width + w > column_count:
                # Generic local adaptation for insert/reorder:
                # If the row starts with a small tile, we can keep an overflowing
                # tile in this row only when equal-splitting still respects the
                # smallest baseline tile width in the proposed row.
                proposed_row_widths = [int(item["w"]) for item in current_row] + [w]
                proposed_tile_count = len(proposed_row_widths)
                proposed_equalized_base_width = column_count // proposed_tile_count
                smallest_baseline_width = min(proposed_row_widths)
                row_is_already_full = current_row_width >= column_count
                can_adapt_overflow_in_row = (
                    current_row[0]["w"] <= column_count // 2
                    and w < column_count
                    and proposed_equalized_base_width >= smallest_baseline_width
                    and not (row_is_already_full and len(current_row) >= 3)
                )
                has_single_full_width_tile = len(current_row) == 1 and current_row[0]["w"] == column_count

                if not has_single_full_width_tile and can_adapt_overflow_in_row:
                    # Keep this tile in the same row; widths will be equalized later.
                    current_row.append({"tile": tile, "h": h, "w": w})
                    current_row_width += w
                    continue

                rows.append(current_row)
                current_row = []
                current_row_width = 0

            current_row.append({"tile": tile, "h": h, "w": w})
            current_row_width += w

        if current_row:
            rows.append(current_row)

        def _find_next_row_y(candidate_y: int, row_height: int) -> int:
            """Push a row down until it no longer overlaps fixed non-insight tiles."""
            y_position = candidate_y
            while True:
                conflicting_bottom: int | None = None
                row_bottom = y_position + row_height
                for span_start, span_end in fixed_non_insight_vertical_spans:
                    if y_position < span_end and row_bottom > span_start:
                        conflicting_bottom = (
                            span_end if conflicting_bottom is None else max(conflicting_bottom, span_end)
                        )
                if conflicting_bottom is None:
                    return y_position
                y_position = conflicting_bottom

        y = 0
        layout_updates: list[ReflowTileLayoutUpdate] = []
        for row in rows:
            row_height = max(item["h"] for item in row)
            row_width = sum(item["w"] for item in row)
            has_single_full_width_tile = len(row) == 1 and row[0]["w"] == column_count
            y = _find_next_row_y(y, row_height)

            target_widths: list[int]
            if has_single_full_width_tile:
                target_widths = [row[0]["w"]]
            elif row_width != column_count:
                tile_count = len(row)
                base_width = column_count // tile_count
                remainder = column_count % tile_count
                target_widths = [base_width + (1 if index < remainder else 0) for index in range(tile_count)]
            else:
                target_widths = [item["w"] for item in row]

            x = 0

            for item, target_width in zip(row, target_widths):
                row_tile = item["tile"]
                h = item["h"] if has_single_full_width_tile else row_height
                w = target_width
                raw_xs_h = ((row_tile.layouts or {}).get("xs") or {}).get("h")
                # Keep existing mobile height for existing tiles; default only for new/invalid layouts.
                xs_h = int(raw_xs_h) if isinstance(raw_xs_h, int | float) and raw_xs_h > 0 else 5
                layouts = {
                    "sm": {"h": h, "w": w, "x": x, "y": y, "minH": 1, "minW": 1},
                    "xs": {"h": xs_h, "w": 1, "x": 0, "y": xs_y, "minH": 1, "minW": 1},
                }
                layout_updates.append({"tile": row_tile, "layouts": layouts})
                x += w
                xs_y += xs_h
            y += row_height

        return layout_updates

    async def _format_dashboard_output(
        self,
        dashboard: Dashboard,
        insights: list[Insight],
    ) -> str:
        """Format dashboard output using DashboardContext for consistency."""
        insights_data: list[DashboardInsightContext] = []
        for insight in insights:
            query_obj = InsightContext.extract_query(insight)
            if query_obj is None:
                continue
            insights_data.append(
                DashboardInsightContext(
                    query=query_obj,
                    name=insight.name or insight.derived_name,
                    description=insight.description,
                    short_id=insight.short_id,
                    db_id=insight.id,
                )
            )

        context = DashboardContext(
            team=self._team,
            insights_data=insights_data,
            name=dashboard.name,
            description=dashboard.description,
            dashboard_id=str(dashboard.id),
        )

        return await context.format_schema()

    async def _get_dashboard(self, dashboard_id: Any) -> Dashboard:
        """Get the dashboard and sorted tiles for the given dashboard ID."""
        # LLMs sometimes output IDs as floats (e.g., "642161.0"), so we parse to int
        try:
            parsed_id = int(float(dashboard_id))
        except (ValueError, TypeError):
            raise MaxToolFatalError(DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=dashboard_id))
        try:
            dashboard = await Dashboard.objects.aget(id=parsed_id, team=self._team, deleted=False)
        except Dashboard.DoesNotExist:
            raise MaxToolFatalError(DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=dashboard_id))

        await self.check_object_access(dashboard, "editor", action="edit")

        return dashboard

    async def _get_dashboard_sorted_tiles(self, dashboard: Dashboard) -> list[DashboardTile]:
        """
        Get the sorted tiles for the given dashboard.
        """
        sorted_tiles = DashboardTile.sort_tiles_by_layout(
            [tile async for tile in DashboardTile.objects.filter(dashboard=dashboard).select_related("insight")]
        )
        return sorted_tiles

    async def _get_update_diff(self, dashboard_tiles: list[DashboardTile], insight_ids: list[str]) -> UpdateDiff:
        """
        Get the update diff for the given dashboard tiles and insight IDs. Returns a list of deleted tiles, created insights, and replaced tiles with their corresponding visualization artifacts.
        """
        if self._cached_update_diff is not None:
            return self._cached_update_diff

        if not insight_ids:
            return UpdateDiff(
                deleted=[],
                created=[],
            )

        existing_ids = {tile.insight.short_id for tile in dashboard_tiles if tile.insight is not None}
        new_ids = set(insight_ids)
        deleted_ids = list(existing_ids - new_ids)
        created_ids = list(new_ids - existing_ids)

        self._cached_update_diff = UpdateDiff(
            deleted=[
                tile for tile in dashboard_tiles if tile.insight is not None and tile.insight.short_id in deleted_ids
            ],
            created=await self._get_visualization_artifacts(created_ids),
        )

        return self._cached_update_diff

    async def _get_visualization_artifacts(self, insight_ids: list[str]) -> list[VisualizationWithSourceResult]:
        """
        Fetch and validate visualization artifacts for the given insight IDs.
        """
        artifacts = await self._context_manager.artifacts.aget_visualizations(self._state.messages, insight_ids)
        not_found = [insight_id for insight_id, artifact in zip(insight_ids, artifacts) if artifact is None]
        if not_found:
            raise MaxToolRetryableError(format_prompt_string(MISSING_INSIGHT_IDS_PROMPT, missing_ids=not_found))
        return cast(list[VisualizationWithSourceResult], artifacts)
