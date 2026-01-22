from typing import Any, Literal, TypedDict, cast

from django.db import transaction

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DataTableNode, HogQLQuery, InsightVizNode, QuerySchemaRoot

from posthog.models import Dashboard, DashboardTile, Insight
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.types import ModelArtifactResult, VisualizationWithSourceResult
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.upsert_dashboard.prompts import (
    CREATE_NO_INSIGHTS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    MISSING_INSIGHT_IDS_PROMPT,
    NO_PERMISSION_PROMPT,
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
        description="The IDs of the insights for the dashboard. Replaces all existing insights. Order determines positional mapping for layout preservation.",
        default=None,
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
            return "\n".join(items)

        created_insights = join([get_artifact_name(artifact) for artifact in diff["created"]])
        deleted_insights = join(
            [get_insight_name(tile.insight) for tile in diff["deleted"] if tile.insight is not None]
        )

        return format_prompt_string(
            PERMISSION_REQUEST_PROMPT,
            dashboard_name=dashboard.name or f"Dashboard #{dashboard.id}",
            new_dashboard_name=action.name,
            new_dashboard_description=action.description,
            deleted_insights=deleted_insights,
            new_insights=created_insights,
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

        insights = self._resolve_insights(cast(list[VisualizationWithSourceResult], artifacts))

        if not insights:
            return CREATE_NO_INSIGHTS_PROMPT, None

        dashboard = await self._create_dashboard_with_tiles(action.name, action.description, insights)
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

        dashboard = await self._update_dashboard_with_tiles(
            dashboard,
            action.name,
            action.description,
            insight_ids,
            artifacts,
        )

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
    def _check_user_permissions(self, dashboard: Dashboard) -> bool | None:
        """Check if user has permission to edit the dashboard."""
        user_access_control = UserAccessControl(user=self._user, team=self._team)
        access_level = user_access_control.get_user_access_level(dashboard)
        return access_level and access_level_satisfied_for_resource("dashboard", access_level, "editor")

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
    ) -> Dashboard:
        """Update dashboard tiles based on provided insight IDs.

        Args:
            dashboard: The dashboard to update
            name: New dashboard name (if provided)
            description: New dashboard description (if provided)
            insight_ids: Ordered list of insight IDs for the dashboard
            artifacts: Resolved visualization artifacts matching insight_ids order
        """
        if name is not None:
            dashboard.name = name
        if description is not None:
            dashboard.description = description
        if name is not None or description is not None:
            dashboard.save(update_fields=["name", "description"])

        if not insight_ids:
            return dashboard

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

        # 2. Create new tiles or restore soft deleted
        for insight_id, insight in zip(insight_ids, resolved_insights):
            existing_tile = short_id_to_tile.get(insight_id)

            if existing_tile:
                # Restore if soft deleted
                if existing_tile.deleted:
                    existing_tile.deleted = False
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

        # 3. Soft delete tiles not in the new list
        tiles_to_delete = [t.id for t in all_tiles if t.id not in active_tile_ids and not t.deleted]
        if tiles_to_delete:
            DashboardTile.objects.filter(id__in=tiles_to_delete).update(deleted=True)

        # 4. Update coordinates based on insight_ids order, keeping original sizes
        # 2-column flow layout: tiles flow left-to-right, respecting their widths
        # Track current Y position for each column
        left_y = 0  # Column at x=0
        right_y = 0  # Column at x=6
        xs_y = 0  # For xs breakpoint (single column)

        for tile in tiles_to_update:
            sm_layout = (tile.layouts or {}).get("sm", {})

            # Keep original sizes, use defaults if not set
            h = sm_layout.get("h", 5)
            w = sm_layout.get("w", 6)

            if w > 6:
                # Wide tile: spans full width, place below both columns
                y = max(left_y, right_y)
                x = 0
                left_y = right_y = y + h
            else:
                # Half-width tile: place in the column with lower Y (left-to-right flow)
                if left_y <= right_y:
                    x = 0
                    y = left_y
                    left_y += h
                else:
                    x = 6
                    y = right_y
                    right_y += h

            tile.layouts = {
                "sm": {"h": h, "w": w, "x": x, "y": y, "minH": 1, "minW": 1},
                "xs": {"h": 5, "w": 1, "x": 0, "y": xs_y, "minH": 1, "minW": 1},
            }
            tile.save(update_fields=["layouts", "deleted"])
            xs_y += 5

        return dashboard

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
        try:
            dashboard = await Dashboard.objects.aget(id=dashboard_id, team=self._team, deleted=False)
        except Dashboard.DoesNotExist:
            raise MaxToolFatalError(DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=dashboard_id))

        permission_result = await self._check_user_permissions(dashboard)
        if not permission_result:
            raise MaxToolFatalError(NO_PERMISSION_PROMPT)

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
