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

    async def test_update_dashboard_replaces_insights_by_default(self):
        """Test that providing insight_ids replaces all insights on the dashboard."""
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
        )

        await tool._arun_impl(action)

        # Only the new insight should remain (old one is soft-deleted)
        tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0].insight_id, new_insight.id)

    async def test_update_dashboard_with_multiple_insights_replaces_all(self):
        """Test that insight_ids replaces all existing insights with the new ones."""
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
        )

        await tool._arun_impl(action)

        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 1)
        self.assertEqual(active_tiles[0].insight_id, new_insight.id)

        # Old tiles should be soft-deleted
        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        # 1 active (reused first tile) + 1 soft-deleted (second old tile)
        self.assertEqual(len(all_tiles), 2)

        soft_deleted_tiles = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(soft_deleted_tiles), 1)

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
            name="Updated Name",
            description="Updated description",
        )

        await tool._arun_impl(action)

        await dashboard.arefresh_from_db()
        self.assertEqual(dashboard.name, "Updated Name")
        self.assertEqual(dashboard.description, "Updated description")

    async def test_positional_replacement_preserves_layout(self):
        """Test that positional replacement preserves tile layouts.

        When replacing insights, the first new insight takes the first tile's layout,
        second takes the second, etc.
        """
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Layouts",
            created_by=self.user,
        )

        # Create insights with specific layouts
        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")

        layout_a = {"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        layout_b = {"sm": {"x": 6, "y": 0, "w": 6, "h": 5}}

        tile_a = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts=layout_a, color="blue"
        )
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_b, layouts=layout_b, color="white")

        original_tile_a_id = tile_a.id

        # Create new insights to replace existing ones
        insight_a_new = await self._create_insight("Insight A New")
        insight_b_new = await self._create_insight("Insight B New")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_a_new.short_id, insight_b_new.short_id],
        )

        await tool._arun_impl(action)

        # Verify tiles are updated in place with preserved layouts
        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard).order_by("id")]
        self.assertEqual(len(active_tiles), 2)

        # First tile should have new insight but same layout/color
        self.assertEqual(active_tiles[0].insight_id, insight_a_new.id)
        self.assertEqual(active_tiles[0].layouts, layout_a)
        self.assertEqual(active_tiles[0].color, "blue")
        self.assertEqual(active_tiles[0].id, original_tile_a_id)

        # Second tile should have new insight but same layout/color
        self.assertEqual(active_tiles[1].insight_id, insight_b_new.id)
        self.assertEqual(active_tiles[1].layouts, layout_b)
        self.assertEqual(active_tiles[1].color, "white")

    async def test_positional_replacement_with_fewer_insights_soft_deletes_extras(self):
        """Test that when new list is shorter, extra tiles are soft-deleted."""
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard to Shrink",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")
        insight_c = await self._create_insight("Insight C")

        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_a, layouts={})
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_b, layouts={})
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_c, layouts={})

        # Replace 3 insights with just 1
        insight_new = await self._create_insight("New Single Insight")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_new.short_id],
        )

        await tool._arun_impl(action)

        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 1)
        self.assertEqual(active_tiles[0].insight_id, insight_new.id)

        # Two tiles should be soft-deleted
        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 3)
        soft_deleted = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(soft_deleted), 2)

    async def test_positional_replacement_with_more_insights_creates_new_tiles(self):
        """Test that when new list is longer, new tiles are created."""
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard to Expand",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_a, layouts={})

        # Replace 1 insight with 3
        insight_new1 = await self._create_insight("New Insight 1")
        insight_new2 = await self._create_insight("New Insight 2")
        insight_new3 = await self._create_insight("New Insight 3")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_new1.short_id, insight_new2.short_id, insight_new3.short_id],
        )

        await tool._arun_impl(action)

        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard).order_by("id")]
        self.assertEqual(len(active_tiles), 3)
        self.assertEqual(active_tiles[0].insight_id, insight_new1.id)
        self.assertEqual(active_tiles[1].insight_id, insight_new2.id)
        self.assertEqual(active_tiles[2].insight_id, insight_new3.id)

    def test_is_dangerous_operation_with_insight_ids(self):
        """Test that providing insight_ids is flagged as a dangerous operation."""
        tool = self._create_tool()

        # insight_ids should be dangerous (since it replaces)
        action_with_insights = UpdateDashboardToolArgs(
            dashboard_id="123",
            insight_ids=["new_id"],
        )
        self.assertTrue(tool.is_dangerous_operation(action=action_with_insights))

        # Just updating name/description should NOT be dangerous
        action_metadata = UpdateDashboardToolArgs(
            dashboard_id="123",
            name="New Name",
            description="New description",
        )
        self.assertFalse(tool.is_dangerous_operation(action=action_metadata))

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

    async def test_positional_replacement_preserves_all_tile_properties(self):
        """
        Test that positional replacement preserves the original tile's layout, color, and ID.

        When replacing insights, tiles are updated in place (insight reference swapped).
        This preserves:
        - The tile ID (critical for frontend's react-grid-layout)
        - The layouts (grid position for each breakpoint)
        - The color styling

        This ensures the dashboard layout remains stable.
        """
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Layouts",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")

        # Create tiles with specific layouts and colors to verify preservation
        original_layout_a = {
            "lg": {"x": 0, "y": 0, "w": 6, "h": 5},
            "sm": {"x": 0, "y": 0, "w": 6, "h": 5},
        }
        original_layout_b = {
            "lg": {"x": 6, "y": 0, "w": 6, "h": 5},
            "sm": {"x": 0, "y": 5, "w": 6, "h": 5},
        }
        tile_a = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts=original_layout_a, color="blue"
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_b, layouts=original_layout_b, color="white"
        )

        original_tile_a_id = tile_a.id

        # Create replacement insights
        insight_a_replacement = await self._create_insight("Insight A Replacement")
        insight_b_replacement = await self._create_insight("Insight B Replacement")

        tool = self._create_tool()

        # Replace both insights positionally
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_a_replacement.short_id, insight_b_replacement.short_id],
        )

        await tool._arun_impl(action)

        # Fetch the new tile for the replacement insight
        replacement_tile = await DashboardTile.objects.aget(dashboard=dashboard, insight=insight_a_replacement)

        # The replacement tile should have the same layout, color, and ID as the original
        self.assertEqual(replacement_tile.layouts, original_layout_a)
        self.assertEqual(replacement_tile.color, "blue")
        self.assertEqual(replacement_tile.id, original_tile_a_id)

        # Verify second tile also preserved its properties
        tile_b = await DashboardTile.objects.aget(dashboard=dashboard, insight=insight_b_replacement)
        self.assertEqual(tile_b.layouts, original_layout_b)
        self.assertEqual(tile_b.color, "white")
