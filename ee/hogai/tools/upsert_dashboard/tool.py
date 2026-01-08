from typing import Literal

from django.db import transaction

import structlog
from pydantic import BaseModel, Field

from posthog.schema import ArtifactSource, DataTableNode, HogQLQuery, InsightVizNode, QuerySchemaRoot

from posthog.models import Dashboard, DashboardTile, Insight
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.manager import ArtifactManager, DatabaseArtifactResult, ModelArtifactResult, StateArtifactResult
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tools.upsert_dashboard.prompts import (
    CREATE_NO_INSIGHTS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    MISSING_INSIGHTS_NOTE_PROMPT,
    NO_PERMISSION_PROMPT,
    UPDATE_NO_CHANGES_PROMPT,
    UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE,
    UPSERT_DASHBOARD_TOOL_PROMPT,
)

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
        description="The IDs of the insights to be included in the dashboard. It might be a mix of existing and new insights.",
        default=None,
    )
    replace_insights: bool | None = Field(
        description="When False (default), appends provided insights to existing ones. When True, the dashboard will contain exactly the insights in insight_ids (others are removed).",
        default=False,
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


class UpsertDashboardTool(MaxTool):
    name: Literal["upsert_dashboard"] = "upsert_dashboard"
    description: str = UPSERT_DASHBOARD_TOOL_PROMPT
    context_prompt_template: str = UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE

    args_schema: type[BaseModel] = UpsertDashboardToolArgs

    def get_required_resource_access(self):
        return [("dashboard", "editor")]

    async def _arun_impl(self, action: UpsertDashboardAction) -> tuple[str, ToolMessagesArtifact | None]:
        if isinstance(action, CreateDashboardToolArgs):
            return await self._handle_create(action)
        else:
            return await self._handle_update(action)

    async def _handle_create(self, action: CreateDashboardToolArgs) -> tuple[str, ToolMessagesArtifact | None]:
        """Handle CREATE action: create a new dashboard with insights."""
        insights, missing_ids = await self._resolve_insights(action.insight_ids)

        if not insights:
            return CREATE_NO_INSIGHTS_PROMPT, None

        dashboard = await self._create_dashboard_with_tiles(action.name, action.description, insights)
        output = await self._format_dashboard_output(dashboard, insights, missing_ids)

        return output, None

    async def _handle_update(self, action: UpdateDashboardToolArgs) -> tuple[str, ToolMessagesArtifact | None]:
        """Handle UPDATE action: update an existing dashboard."""
        try:
            dashboard = await Dashboard.objects.aget(id=action.dashboard_id, team=self._team, deleted=False)
        except Dashboard.DoesNotExist:
            return DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=action.dashboard_id), None

        permission_result = await self._check_user_permissions(dashboard)
        if not permission_result:
            return NO_PERMISSION_PROMPT, None

        insights, missing_ids = await self._resolve_insights(action.insight_ids or [])

        if not insights and not action.name and action.description is None:
            return UPDATE_NO_CHANGES_PROMPT, None

        dashboard = await self._update_dashboard_with_tiles(
            dashboard, insights, action.replace_insights or False, action.name, action.description
        )

        all_insights = [
            i
            async for i in Insight.objects.filter(
                team=self._team, dashboard_tiles__dashboard=dashboard, dashboard_tiles__deleted=False, deleted=False
            )
        ]

        output = await self._format_dashboard_output(dashboard, all_insights, missing_ids)

        return output, None

    async def _resolve_insights(self, insight_ids: list[str]) -> tuple[list[Insight], list[str]]:
        """
        Resolve insight_ids using ArtifactManager.aget_insights_with_source.
        Returns (resolved_insights, missing_ids) in same order as input.

        For State/Artifact sources, creates and saves new Insights before adding to dashboard.
        """
        artifact_manager = ArtifactManager(self._team, self._user, self._config)
        results = await artifact_manager.aget_insights_with_source(self._state.messages, insight_ids)

        resolved: list[Insight] = []
        missing: list[str] = []

        for insight_id, result in zip(insight_ids, results):
            if result is None:
                missing.append(insight_id)
            elif isinstance(result, ModelArtifactResult) and result.source == ArtifactSource.INSIGHT:
                resolved.append(result.model)
            elif isinstance(result, StateArtifactResult | DatabaseArtifactResult):
                # Need to create and save insight from artifact content
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
        replace: bool,
        name: str | None,
        description: str | None,
    ) -> Dashboard:
        """Update an existing dashboard with new tiles."""
        if name is not None:
            dashboard.name = name
        if description is not None:
            dashboard.description = description
        if name is not None or description is not None:
            dashboard.save(update_fields=["name", "description"])

        # Create new insights if they don't exist
        insights = self._create_resolved_insights(insights)

        insight_ids = {i.id for i in insights}
        # Fetch all existing tiles (including soft-deleted) in one query
        existing_tiles = {
            tile.insight_id: tile for tile in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)
        }

        if replace:
            # Soft-delete tiles for insights not in the new set
            tiles_to_soft_delete = [t for iid, t in existing_tiles.items() if iid not in insight_ids and not t.deleted]
            if tiles_to_soft_delete:
                DashboardTile.objects_including_soft_deleted.filter(id__in=[t.id for t in tiles_to_soft_delete]).update(
                    deleted=True
                )

        # Un-delete existing soft-deleted tiles
        tiles_to_undelete = [
            existing_tiles[i.id] for i in insights if i.id in existing_tiles and existing_tiles[i.id].deleted
        ]
        if tiles_to_undelete:
            DashboardTile.objects_including_soft_deleted.filter(id__in=[t.id for t in tiles_to_undelete]).update(
                deleted=False
            )

        # Bulk create new tiles
        new_insights = [i for i in insights if i.id not in existing_tiles]
        if new_insights:
            DashboardTile.objects.bulk_create(
                [
                    DashboardTile(dashboard=dashboard, insight=insight, deleted=False, layouts={})
                    for insight in new_insights
                ]
            )

        return dashboard

    async def _format_dashboard_output(
        self, dashboard: Dashboard, insights: list[Insight], missing_ids: list[str] | None = None
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
