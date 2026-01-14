from typing import Any, Literal, TypedDict, cast

from django.db import transaction

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DataTableNode, HogQLQuery, InsightVizNode, QuerySchemaRoot

from posthog.models import Dashboard, DashboardTile, Insight
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import ModelArtifactResult, VisualizationWithSourceResult
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.upsert_dashboard.prompts import (
    CREATE_NO_INSIGHTS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    MISSING_INSIGHTS_NOTE_PROMPT,
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
            _, sorted_tiles = await self._get_dashboard_and_sorted_tiles(action.dashboard_id)
            diff = await self._get_update_diff(sorted_tiles, action.insight_ids)
            return len(diff["deleted"]) > 0 or len(diff["replaced"]) > 0
        return False

    async def format_dangerous_operation_preview(self, *, action: UpsertDashboardAction, **kwargs) -> str:
        """
        Build a rich preview showing dashboard details and what will be modified.
        """
        if isinstance(action, CreateDashboardToolArgs):
            raise MaxToolFatalError("Create dashboard operation is not dangerous.")

        dashboard, sorted_tiles = await self._get_dashboard_and_sorted_tiles(action.dashboard_id)
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
        insights, missing_ids = await self._resolve_insights(action.insight_ids)

        if not insights:
            return CREATE_NO_INSIGHTS_PROMPT, None

        dashboard = await self._create_dashboard_with_tiles(action.name, action.description, insights)
        output = await self._format_dashboard_output(dashboard, insights, missing_ids)

        return output, {"dashboard_id": dashboard.id}

    async def _handle_update(self, action: UpdateDashboardToolArgs) -> tuple[str, dict | None]:
        """Handle UPDATE action: update an existing dashboard."""
        try:
            dashboard = await Dashboard.objects.aget(id=action.dashboard_id, team=self._team, deleted=False)
        except Dashboard.DoesNotExist:
            return DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=action.dashboard_id), None

        permission_result = await self._check_user_permissions(dashboard)
        if not permission_result:
            return NO_PERMISSION_PROMPT, None

        insights, missing_ids = await self._resolve_insights(action.insight_ids or [])

        has_changes = insights or action.name is not None or action.description is not None
        if not has_changes:
            return UPDATE_NO_CHANGES_PROMPT, None

        dashboard = await self._update_dashboard_with_tiles(
            dashboard,
            insights,
            action.name,
            action.description,
        )

        all_insights = [
            i
            async for i in Insight.objects.filter(
                team=self._team,
                dashboard_tiles__dashboard=dashboard,
                dashboard_tiles__deleted=False,
                deleted=False,
            )
        ]

        output = await self._format_dashboard_output(dashboard, all_insights, missing_ids)

        return output, {"dashboard_id": dashboard.id}

    async def _resolve_insights(self, insight_ids: list[str]) -> tuple[list[Insight], list[str]]:
        """
        Resolve insight_ids using VisualizationHandler.
        Returns (resolved_insights, missing_ids) in same order as input.

        For State/Artifact sources, creates and saves new Insights before adding to dashboard.
        """
        artifact_manager = ArtifactManager(self._team, self._user, self._config)
        results = await artifact_manager.aget_visualizations(self._state.messages, insight_ids)

        resolved: list[Insight] = []
        missing: list[str] = []

        for insight_id, result in zip(insight_ids, results):
            if result is None:
                missing.append(insight_id)
            elif isinstance(result, ModelArtifactResult):
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

        return resolved, missing

    def _create_resolved_insights(self, results: list[Insight]) -> list[Insight]:
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
        insights: list[Insight],
        name: str | None,
        description: str | None,
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

        if not insights:
            return dashboard

        # Create new insights if they don't exist
        insights = self._create_resolved_insights(insights)

        # Get existing tiles sorted by layout position
        # DashboardTile.objects already excludes deleted=True via DashboardTileManager
        existing_tiles = list(DashboardTile.objects.filter(dashboard=dashboard).select_related("insight"))
        sorted_tiles = DashboardTile.sort_tiles_by_layout(existing_tiles)

        # Positional replacement: sorted_tiles[i] → insights[i]
        # Update tiles in-place to preserve layout/color
        new_insights_to_create: list[Insight] = []

        for i, new_insight in enumerate(insights):
            if i < len(sorted_tiles):
                # Update existing tile in-place using queryset update to preserve layout, color, tile ID
                tile = sorted_tiles[i]
                DashboardTile.objects_including_soft_deleted.filter(id=tile.id).update(insight=new_insight)
            else:
                # Need to create a new tile for this insight
                new_insights_to_create.append(new_insight)

        # Soft-delete extra tiles (when new list is shorter than old)
        if len(sorted_tiles) > len(insights):
            tiles_to_delete = sorted_tiles[len(insights) :]
            DashboardTile.objects.filter(id__in=[t.id for t in tiles_to_delete]).update(deleted=True)

        # Create tiles for extra insights (when new list is longer than old)
        if new_insights_to_create:
            DashboardTile.objects.bulk_create(
                [
                    DashboardTile(dashboard=dashboard, insight=insight, deleted=False, layouts={})
                    for insight in new_insights_to_create
                ]
            )

        return dashboard

    async def _format_dashboard_output(
        self,
        dashboard: Dashboard,
        insights: list[Insight],
        missing_ids: list[str] | None = None,
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

        result = await context.format_schema()

        if missing_ids:
            result += "\n\n" + MISSING_INSIGHTS_NOTE_PROMPT.format(missing_ids=", ".join(missing_ids))

        return result

    async def _get_dashboard_and_sorted_tiles(self, dashboard_id: Any) -> tuple[Dashboard, list[DashboardTile]]:
        """Get the dashboard and sorted tiles for the given dashboard ID."""
        try:
            dashboard = await Dashboard.objects.aget(id=dashboard_id, team=self._team, deleted=False)
        except Dashboard.DoesNotExist:
            raise MaxToolFatalError(DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=dashboard_id))

        sorted_tiles = DashboardTile.sort_tiles_by_layout(
            [tile async for tile in DashboardTile.objects.filter(dashboard=dashboard).select_related("insight")]
        )

        return dashboard, sorted_tiles

    async def _get_visualization_artifacts(self, insight_ids: list[str]) -> list[VisualizationWithSourceResult]:
        """
        Fetch and validate visualization artifacts for the given insight IDs.
        """
        artifacts = await self._context_manager.artifacts.aget_visualizations(self._state.messages, insight_ids)
        not_found = [insight_id for insight_id, artifact in zip(insight_ids, artifacts) if artifact is None]
        if not_found:
            raise MaxToolRetryableError(
                f"Some insights were not found in the conversation artifacts: {not_found}. You should check if the provided insight_ids are correct."
            )
        return cast(list[VisualizationWithSourceResult], artifacts)

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

        # Find new insights.
        created_insights = [insight_id for insight_id in insight_ids if insight_id not in dashboard_insights]

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
