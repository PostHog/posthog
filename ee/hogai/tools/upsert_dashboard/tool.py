from typing import Literal

from django.db import transaction
from django.db.models import Q

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DataTableNode, HogQLQuery, InsightVizNode, QuerySchemaRoot

from posthog.models import Dashboard, DashboardTile, Insight
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import ModelArtifactResult
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool
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


def _track_replacements(original_ids: list[str], new_ids: list[str]) -> dict[str, str | None]:
    """Map original insight IDs to new insight IDs based on position."""
    result: dict[str, str | None] = {}
    for i, orig_id in enumerate(original_ids):
        result[orig_id] = new_ids[i] if i < len(new_ids) else None
    return result


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


class UpsertDashboardTool(MaxTool):
    name: Literal["upsert_dashboard"] = "upsert_dashboard"
    description: str = UPSERT_DASHBOARD_TOOL_PROMPT
    context_prompt_template: str = UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE

    args_schema: type[BaseModel] = UpsertDashboardToolArgs

    def get_required_resource_access(self):
        return [("dashboard", "editor")]

    async def is_dangerous_operation(self, *, action: UpsertDashboardAction, **kwargs) -> bool:
        """Update operations that replace existing insights are dangerous."""
        if isinstance(action, UpdateDashboardToolArgs):
            return bool(action.insight_ids)
        return False

    async def format_dangerous_operation_preview(self, *, action: UpsertDashboardAction, **kwargs) -> str:
        """
        Build a rich preview showing dashboard details and what will be modified.
        """
        # Fetch dashboard details for richer preview
        dashboard_name = f"Dashboard #{action.dashboard_id}"
        existing_insight_count = 0
        existing_insight_names: list[str] = []
        existing_insights: list[Insight] = []

        try:
            dashboard = await Dashboard.objects.aget(id=action.dashboard_id, team=self._team, deleted=False)
            dashboard_name = dashboard.name or dashboard_name

            # TRICKY: All conditions on `dashboard_tiles__*` must be in a single .filter() call.
            # Chaining separate .filter() calls that span multi-valued relationships causes Django
            # to create separate JOINs, which can match different tiles for each condition.
            existing_insights = [
                i
                async for i in Insight.objects.filter(
                    Q(dashboard_tiles__dashboard=dashboard)
                    & (Q(dashboard_tiles__deleted=False) | Q(dashboard_tiles__deleted__isnull=True)),
                    team=self._team,
                    deleted=False,
                ).distinct()
            ]
            existing_insight_count = len(existing_insights)
            existing_insight_names = [i.name or i.derived_name or f"Insight #{i.id}" for i in existing_insights[:5]]
        except Dashboard.DoesNotExist:
            pass
        except Exception as e:
            logger.exception(f"Error fetching dashboard details for preview: {e}")

        # Build detailed preview
        lines = [f"Dashboard: {dashboard_name}"]

        if action.name and action.name != dashboard_name:
            lines.append(f"Rename to: '{action.name}'")

        if action.description is not None:
            lines.append("Update description")

        if action.update_insight_ids:
            # Surgical update: show which insights will be modified
            update_count = len(action.update_insight_ids)
            lines.append("")
            lines.append(f"UPDATE {update_count} insight(s) on this dashboard")

            # Try to find the names of insights being updated
            old_insight_ids = list(action.update_insight_ids.keys())
            insights_to_update = [i for i in existing_insights if i.short_id in old_insight_ids]
            if insights_to_update:
                lines.append("")
                lines.append("Insights that will be MODIFIED:")
                for insight in insights_to_update[:5]:
                    name = insight.name or insight.derived_name or f"Insight #{insight.id}"
                    lines.append(f"  • {name}")
                if len(insights_to_update) > 5:
                    lines.append(f"  • ... and {len(insights_to_update) - 5} more")
            else:
                # Fallback if we couldn't resolve the insight names
                lines.append("")
                lines.append("Insight IDs being modified:")
                for old_id in old_insight_ids[:5]:
                    lines.append(f"  • {old_id}")
                if len(old_insight_ids) > 5:
                    lines.append(f"  • ... and {len(old_insight_ids) - 5} more")

        elif action.replace_insights:
            new_count = len(action.insight_ids) if action.insight_ids else 0
            lines.append("")
            lines.append(f"REPLACE all {existing_insight_count} existing insight(s) with {new_count} new insight(s)")

            if existing_insight_names:
                lines.append("")
                lines.append("Insights that will be REMOVED:")
                for name in existing_insight_names:
                    lines.append(f"  • {name}")
                if existing_insight_count > 5:
                    lines.append(f"  • ... and {existing_insight_count - 5} more")

        return "\n".join(lines)

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
