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
    replaced: list[tuple[DashboardTile, VisualizationWithSourceResult]]


class UpsertDashboardTool(MaxTool):
    name: Literal["upsert_dashboard"] = "upsert_dashboard"
    description: str = UPSERT_DASHBOARD_TOOL_PROMPT
    context_prompt_template: str = UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE
    args_schema: type[BaseModel] = UpsertDashboardToolArgs
    _cached_update_diff: UpdateDiff | None = None

    def get_required_resource_access(self):
        return [("dashboard", "editor")]

    async def is_dangerous_operation(self, *, action: UpsertDashboardAction, **kwargs) -> bool:
        """Update operations that replace existing insights are dangerous."""
        if isinstance(action, UpdateDashboardToolArgs) and action.insight_ids:
            dashboard = await self._get_dashboard(action.dashboard_id)
            sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
            diff = await self._get_update_diff(sorted_tiles, action.insight_ids)
            return len(diff["deleted"]) > 0 or len(diff["replaced"]) > 0
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
        replaced_insights = join(
            [
                f"{get_insight_name(tile.insight)} -> {get_artifact_name(artifact)}"
                for tile, artifact in diff["replaced"]
                if tile.insight is not None
            ]
        )

        return format_prompt_string(
            PERMISSION_REQUEST_PROMPT,
            dashboard_name=dashboard.name or f"Dashboard #{dashboard.id}",
            new_dashboard_name=action.name,
            new_dashboard_description=action.description,
            deleted_insights=deleted_insights,
            new_insights=created_insights,
            updated_insights=replaced_insights,
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
        sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
        has_changes = action.insight_ids or action.name is not None or action.description is not None
        if not has_changes:
            return UPDATE_NO_CHANGES_PROMPT, None

        diff = await self._get_update_diff(sorted_tiles, action.insight_ids or [])
        dashboard = await self._update_dashboard_with_tiles(
            dashboard,
            action.name,
            action.description,
            diff,
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
        diff: UpdateDiff,
    ) -> Dashboard:
        """Update an existing dashboard with new tiles using positional layout preservation.

        Args:
            dashboard: The dashboard to update
            insights: List of insights to replace the dashboard with (order matters for layout preservation)
            name: New dashboard name (if provided)
            description: New dashboard description (if provided)
        """
        if name is not None:
            dashboard.name = name
        if description is not None:
            dashboard.description = description
        if name is not None or description is not None:
            dashboard.save(update_fields=["name", "description"])

        has_changes = diff["created"] or diff["deleted"] or diff["replaced"]
        if not has_changes:
            return dashboard

        if diff["deleted"]:
            # Delete deleted tiles
            DashboardTile.objects.filter(id__in=[t.id for t in diff["deleted"]]).update(deleted=True)

        # Replace tiles with new insights using layout swapping
        # For existing insights: keep them on their current tiles, just update layouts
        # For new insights: assign them to tiles whose insights are being removed
        if diff["replaced"]:
            replaced_resolved_insights = self._create_resolved_insights(
                self._resolve_insights([artifact for _, artifact in diff["replaced"]])
            )

            # Map: insight_id -> current tile (before any changes)
            current_insight_to_tile = {tile.insight_id: tile for tile, _ in diff["replaced"] if tile.insight_id}

            # Identify which insights are new vs existing
            current_insight_ids = set(current_insight_to_tile.keys())
            new_insight_ids = {insight.id for insight in replaced_resolved_insights}
            insights_being_removed = current_insight_ids - new_insight_ids
            insights_being_added = new_insight_ids - current_insight_ids

            # Get tiles that will be freed (their insights are being removed)
            # Preserve original position order by iterating through diff["replaced"] in order
            freed_tiles = [tile for tile, _ in diff["replaced"] if tile.insight_id in insights_being_removed]
            freed_tiles_iter = iter(freed_tiles)

            # Ensure all position tiles have valid layouts for proper ordering
            # If layouts are empty, generate sequential positions matching standard format
            for i, (position_tile, _) in enumerate(diff["replaced"]):
                if not position_tile.layouts or not position_tile.layouts.get("sm"):
                    # Generate default layout: full-width tiles stacked vertically
                    position_tile.layouts = {
                        "sm": {"h": 5, "w": 6, "x": 0, "y": i * 5, "minH": 1, "minW": 1},
                        "xs": {"h": 5, "w": 1, "x": 0, "y": i * 5, "minH": 1, "minW": 1},
                    }

            # Process each position
            for (position_tile, _), new_insight in zip(diff["replaced"], replaced_resolved_insights):
                if new_insight.id in insights_being_added:
                    # New insight - assign it to a freed tile
                    tile_to_use = next(freed_tiles_iter)
                    tile_to_use.insight = new_insight
                    tile_to_use.layouts = position_tile.layouts
                    tile_to_use.color = position_tile.color
                    tile_to_use.save()
                else:
                    # Existing insight - update its tile's layout to new position
                    existing_tile = current_insight_to_tile[new_insight.id]
                    existing_tile.layouts = position_tile.layouts
                    existing_tile.color = position_tile.color
                    existing_tile.save(update_fields=["layouts", "color"])

        # Create completely new tiles
        if diff["created"]:
            created_resolved_insights = self._create_resolved_insights(self._resolve_insights(diff["created"]))
            # Calculate starting position based on number of replaced tiles
            num_existing_positions = len(diff["replaced"])
            tiles_to_create = []
            for i, insight in enumerate(created_resolved_insights):
                # Generate layout for proper ordering: tiles flow vertically
                y_position = (num_existing_positions + i) * 5
                tiles_to_create.append(
                    DashboardTile(
                        dashboard=dashboard,
                        insight=insight,
                        layouts={
                            "sm": {"h": 5, "w": 6, "x": 0, "y": y_position, "minH": 1, "minW": 1},
                            "xs": {"h": 5, "w": 1, "x": 0, "y": y_position, "minH": 1, "minW": 1},
                        },
                    )
                )
            DashboardTile.objects.bulk_create(tiles_to_create)

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
                replaced=[],
            )

        # Find existing insights in the dashboard.
        dashboard_insights = {tile.insight.short_id: tile for tile in dashboard_tiles if tile.insight is not None}

        # Map original insight IDs to new insight IDs based on position.
        diff: dict[str, str | None] = {}
        for i, orig_id in enumerate(list(dashboard_insights.keys())):
            diff[orig_id] = insight_ids[i] if i < len(insight_ids) else None

        # Find deleted insights.
        deleted_insights = [
            dashboard_insights[key] for key, value in diff.items() if value is None and key in dashboard_insights
        ]

        # Find replaced insights.
        replaced_insights = [
            (dashboard_insights[key], value)
            for key, value in diff.items()
            if value is not None and key in dashboard_insights
        ]

        # Get insight IDs used in replacements (these reuse existing tiles)
        replaced_insight_ids = {artifact_id for _, artifact_id in replaced_insights}

        # Find new insights that need new tiles (exclude insights used in positional replacements)
        created_insights = [
            insight_id
            for insight_id in insight_ids
            if insight_id not in dashboard_insights and insight_id not in replaced_insight_ids
        ]

        if not created_insights and not replaced_insights:
            return UpdateDiff(
                deleted=deleted_insights,
                created=[],
                replaced=[],
            )

        # Fetch and validate visualization artifacts for the provided insight IDs.
        artifact_mapping = dict(zip(insight_ids, await self._get_visualization_artifacts(insight_ids)))

        self._cached_update_diff = UpdateDiff(
            deleted=deleted_insights,
            created=[artifact_mapping[insight_id] for insight_id in created_insights],
            replaced=[(tile, artifact_mapping[artifact_id]) for tile, artifact_id in replaced_insights],
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
