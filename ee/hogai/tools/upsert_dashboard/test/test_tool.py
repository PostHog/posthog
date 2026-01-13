from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    AssistantHogQLQuery,
    DataTableNode,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    InsightVizNode,
    LifecycleQuery,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
    VisualizationMessage,
)

from posthog.models import Dashboard, DashboardTile, Insight

from ee.hogai.tools.upsert_dashboard.tool import CreateDashboardToolArgs, UpdateDashboardToolArgs, UpsertDashboardTool
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import AgentArtifact, Conversation

DEFAULT_TRENDS_QUERY = TrendsQuery(series=[EventsNode(name="$pageview")])


class TestUpsertDashboardTool(BaseTest):
    def _create_tool(self, state: AssistantState | None = None) -> UpsertDashboardTool:
        if state is None:
            state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        return UpsertDashboardTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

    async def _create_insight(
        self,
        name: str,
        query: Any | None = None,
    ) -> Insight:
        if query is None:
            query = DEFAULT_TRENDS_QUERY
        return await Insight.objects.acreate(
            team=self.team,
            created_by=self.user,
            name=name,
            query=DataTableNode(source=query).model_dump()
            if isinstance(query, HogQLQuery | AssistantHogQLQuery)
            else InsightVizNode(source=query).model_dump(),
            saved=True,
        )

    async def test_create_dashboard_from_scratch_attaches_insights_in_order(self):
        insight1 = await self._create_insight("First Insight")
        insight2 = await self._create_insight("Second Insight")
        insight3 = await self._create_insight("Third Insight")

        tool = self._create_tool()

        action = CreateDashboardToolArgs(
            insight_ids=[insight1.short_id, insight2.short_id, insight3.short_id],
            name="Test Dashboard",
            description="A test dashboard",
        )

        result, _ = await tool._arun_impl(action)

        dashboard = await Dashboard.objects.aget(name="Test Dashboard")
        self.assertEqual(dashboard.description, "A test dashboard")
        self.assertEqual(dashboard.created_by_id, self.user.id)
        self.assertEqual(dashboard.team_id, self.team.id)

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard).order_by("id")]
        self.assertEqual(len(tiles), 3)
        self.assertEqual(tiles[0].insight_id, insight1.id)
        self.assertEqual(tiles[1].insight_id, insight2.id)
        self.assertEqual(tiles[2].insight_id, insight3.id)

        self.assertIn("Test Dashboard", result)
        self.assertIn(str(dashboard.id), result)

    async def test_update_dashboard_append_new_insight(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Existing Dashboard",
            description="Existing description",
            created_by=self.user,
        )

        existing_insight = await self._create_insight("Existing Insight")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=existing_insight, layouts={})

        new_insight = await self._create_insight("New Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
            replace_insights=False,
        )

        await tool._arun_impl(action)

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard).order_by("id")]
        self.assertEqual(len(tiles), 2)
        insight_ids = {t.insight_id for t in tiles}
        self.assertIn(existing_insight.id, insight_ids)
        self.assertIn(new_insight.id, insight_ids)

    async def test_update_dashboard_append_duplicate_insight_is_ignored(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Insight",
            created_by=self.user,
        )

        existing_insight = await self._create_insight("Existing Insight")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=existing_insight, layouts={})

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[existing_insight.short_id],
            replace_insights=False,
        )

        await tool._arun_impl(action)

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0].insight_id, existing_insight.id)

    async def test_update_dashboard_append_insight_with_soft_deleted_tile_restores_it(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Soft-Deleted Tile",
            created_by=self.user,
        )

        insight = await self._create_insight("Soft-Deleted Insight")
        soft_deleted_tile = await DashboardTile.objects_including_soft_deleted.acreate(
            dashboard=dashboard, insight=insight, layouts={}, deleted=True
        )

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight.short_id],
            replace_insights=False,
        )

        await tool._arun_impl(action)

        await soft_deleted_tile.arefresh_from_db()
        self.assertFalse(soft_deleted_tile.deleted)

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0].insight_id, insight.id)

    async def test_update_dashboard_replace_insights(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard to Replace",
            created_by=self.user,
        )

        old_insight1 = await self._create_insight("Old Insight 1")
        old_insight2 = await self._create_insight("Old Insight 2")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=old_insight1, layouts={})
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=old_insight2, layouts={})

        new_insight = await self._create_insight("New Replacement Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
            replace_insights=True,
        )

        await tool._arun_impl(action)

        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 1)
        self.assertEqual(active_tiles[0].insight_id, new_insight.id)

        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 3)

        soft_deleted_tiles = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(soft_deleted_tiles), 2)
        soft_deleted_insight_ids = {t.insight_id for t in soft_deleted_tiles}
        self.assertEqual(soft_deleted_insight_ids, {old_insight1.id, old_insight2.id})

    @parameterized.expand(
        [
            ("trends", TrendsQuery(series=[EventsNode(name="$pageview")])),
            ("funnels", FunnelsQuery(series=[EventsNode(name="step1"), EventsNode(name="step2")])),
            ("retention", RetentionQuery(retentionFilter=RetentionFilter())),
            ("lifecycle", LifecycleQuery(series=[EventsNode(name="$pageview")])),
            ("hogql", HogQLQuery(query="SELECT 1")),
        ]
    )
    async def test_dashboard_accepts_different_insight_types(
        self, _name: str, query: TrendsQuery | FunnelsQuery | RetentionQuery | LifecycleQuery | HogQLQuery
    ):
        insight = await self._create_insight(f"{_name} Insight", query)

        tool = self._create_tool()

        action = CreateDashboardToolArgs(
            insight_ids=[insight.short_id],
            name=f"Dashboard with {_name}",
            description=f"Testing {_name} insight type",
        )

        result, _ = await tool._arun_impl(action)

        dashboard = await Dashboard.objects.aget(name=f"Dashboard with {_name}")
        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0].insight_id, insight.id)

    async def test_update_dashboard_permission_denied_for_restricted_dashboard(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Restricted Dashboard",
            created_by=self.user,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        new_insight = await self._create_insight("New Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
            replace_insights=False,
        )

        # Patch at the class level to return False (no permission)
        async def mock_no_permission(self, dashboard):
            return False

        with patch.object(UpsertDashboardTool, "_check_user_permissions", mock_no_permission):
            result, _ = await tool._arun_impl(action)

        self.assertIn("permission", result.lower())

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 0)

    async def test_update_dashboard_permission_allowed_for_unrestricted_dashboard(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Unrestricted Dashboard",
            created_by=self.user,
            restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )

        new_insight = await self._create_insight("New Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
            replace_insights=False,
        )

        result, _ = await tool._arun_impl(action)

        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0].insight_id, new_insight.id)

    async def test_update_nonexistent_dashboard_returns_error(self):
        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id="99999999",
            insight_ids=["some-id"],
            replace_insights=False,
        )

        result, _ = await tool._arun_impl(action)

        self.assertIn("99999999", result)
        self.assertIn("not found", result.lower())

    async def test_update_deleted_dashboard_returns_error(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Deleted Dashboard",
            created_by=self.user,
            deleted=True,
        )

        new_insight = await self._create_insight("New Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
            replace_insights=False,
        )

        result, _ = await tool._arun_impl(action)

        self.assertIn(str(dashboard.id), result)
        self.assertIn("not found", result.lower())

    async def test_create_dashboard_with_no_valid_insights_returns_error(self):
        tool = self._create_tool()

        action = CreateDashboardToolArgs(
            insight_ids=["nonexistent1", "nonexistent2"],
            name="Empty Dashboard",
            description="Should fail",
        )

        result, _ = await tool._arun_impl(action)

        dashboards = [d async for d in Dashboard.objects.filter(name="Empty Dashboard")]
        self.assertEqual(len(dashboards), 0)

    async def test_update_dashboard_name_and_description(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Original Name",
            description="Original description",
            created_by=self.user,
        )

        insight = await self._create_insight("Some Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight.short_id],
            replace_insights=False,
            name="Updated Name",
            description="Updated description",
        )

        await tool._arun_impl(action)

        await dashboard.arefresh_from_db()
        self.assertEqual(dashboard.name, "Updated Name")
        self.assertEqual(dashboard.description, "Updated description")

    async def test_resolve_insights_preserves_order_with_state_and_database(self):
        # Create a conversation for artifacts
        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)

        # Create an insight in database (will be resolved from Insight model)
        db_insight = await self._create_insight("Database Insight")

        # Create an artifact in database (will be resolved from AgentArtifact)
        artifact_query = TrendsQuery(series=[EventsNode(name="$pageview")])
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=conversation,
            name="Artifact Insight",
            type=AgentArtifact.Type.VISUALIZATION,
            data={
                "query": artifact_query.model_dump(exclude_none=True),
                "name": "Artifact Insight",
                "description": "From artifact",
            },
        )

        # Create a state message (will be resolved from state)
        state_viz_id = str(uuid4())
        state_query = TrendsQuery(series=[EventsNode(name="$identify")])
        state_viz_message = VisualizationMessage(
            id=state_viz_id,
            query="state query",
            answer=state_query,
            plan="state plan",
        )

        state = AssistantState(messages=[state_viz_message], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state)

        # Test ordering: state, artifact, database
        insight_ids = [state_viz_id, artifact.short_id, db_insight.short_id]

        insights, missing = await tool._resolve_insights(insight_ids)

        self.assertEqual(len(insights), 3)
        self.assertEqual(len(missing), 0)

        # Verify order is preserved
        self.assertEqual(insights[0].name, "state query")
        self.assertEqual(insights[1].name, "Artifact Insight")
        self.assertEqual(insights[2].name, "Database Insight")

        # Test different ordering: database, state, artifact
        insight_ids = [db_insight.short_id, state_viz_id, artifact.short_id]
        insights, missing = await tool._resolve_insights(insight_ids)

        self.assertEqual(len(insights), 3)
        self.assertEqual(insights[0].name, "Database Insight")
        self.assertEqual(insights[1].name, "state query")
        self.assertEqual(insights[2].name, "Artifact Insight")
