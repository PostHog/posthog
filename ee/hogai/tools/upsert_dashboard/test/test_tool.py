from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ArtifactSource,
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
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Dashboard, DashboardTile, Insight

from ee.hogai.artifacts.types import ModelArtifactResult
from ee.hogai.context.context import AssistantContextManager
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.upsert_dashboard.tool import CreateDashboardToolArgs, UpdateDashboardToolArgs, UpsertDashboardTool
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import AgentArtifact, Conversation

DEFAULT_TRENDS_QUERY = TrendsQuery(series=[EventsNode(name="$pageview")])


class TestUpsertDashboardTool(BaseTest):
    def _create_tool(self, state: AssistantState | None = None) -> UpsertDashboardTool:
        if state is None:
            state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()

        # Mock aget_visualizations to return ModelArtifactResult for existing insights
        async def mock_aget_visualizations(messages, insight_ids):
            results: list[ModelArtifactResult | None] = []
            for insight_id in insight_ids:
                try:
                    insight = await Insight.objects.aget(short_id=insight_id, team=self.team)
                    query = InsightContext.extract_query(insight)
                    content = VisualizationArtifactContent(
                        query=query,
                        name=insight.name or insight.derived_name,
                        description=insight.description,
                    )
                    results.append(
                        ModelArtifactResult(
                            source=ArtifactSource.INSIGHT,
                            content=content,
                            model=insight,
                        )
                    )
                except Insight.DoesNotExist:
                    results.append(None)
            return results

        context_manager.artifacts.aget_visualizations = AsyncMock(side_effect=mock_aget_visualizations)
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

        # Old tiles should be soft-deleted, new tile created
        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        # 1 active (new) + 2 soft-deleted (old)
        self.assertEqual(len(all_tiles), 3)

        soft_deleted_tiles = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(soft_deleted_tiles), 2)

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
            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(action)

        self.assertIn("permission", str(ctx.exception).lower())

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

    async def test_create_dashboard_with_no_valid_insights_returns_error(self):
        tool = self._create_tool()

        action = CreateDashboardToolArgs(
            insight_ids=["nonexistent1", "nonexistent2"],
            name="Empty Dashboard",
            description="Should fail",
        )

        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._arun_impl(action)

        self.assertIn("nonexistent1", str(ctx.exception))
        self.assertIn("nonexistent2", str(ctx.exception))

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

    async def test_positional_replacement_preserves_sizes(self):
        """Test that replacing insights preserves original tile sizes but updates coordinates.

        When updating a dashboard:
        - Old insights are soft-deleted
        - New insights get new tiles
        - Tile sizes (w, h) from original tiles are preserved via defaults
        - Coordinates (x, y) are updated based on position in insight_ids
        """
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Layouts",
            created_by=self.user,
        )

        # Create insights with specific layouts
        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")

        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}, color="blue"
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_b, layouts={"sm": {"x": 6, "y": 0, "w": 6, "h": 5}}, color="white"
        )

        # Create new insights to replace existing ones
        insight_a_new = await self._create_insight("Insight A New")
        insight_b_new = await self._create_insight("Insight B New")

        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_a_new.short_id, insight_b_new.short_id],
        )

        await tool._arun_impl(action)

        # Old tiles are soft-deleted, new tiles created
        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 2)

        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 4)  # 2 active + 2 soft-deleted

        sorted_tiles = DashboardTile.sort_tiles_by_layout(active_tiles)
        self.assertEqual(sorted_tiles[0].insight_id, insight_a_new.id)
        self.assertEqual(sorted_tiles[1].insight_id, insight_b_new.id)

    @parameterized.expand(
        [
            ("shrink_3_to_1", 3, 1),
            ("expand_1_to_3", 1, 3),
        ]
    )
    async def test_positional_replacement_handles_insight_count_changes(
        self, _name: str, initial_count: int, new_count: int
    ):
        """Test that insight count changes are handled correctly (soft-deletes and creates)."""
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name=f"Dashboard {_name}",
            created_by=self.user,
        )

        initial_insights = [await self._create_insight(f"Initial {i}") for i in range(initial_count)]
        for insight in initial_insights:
            await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight, layouts={})

        new_insights = [await self._create_insight(f"New {i}") for i in range(new_count)]

        tool = self._create_tool()
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight.short_id for insight in new_insights],
        )

        await tool._arun_impl(action)

        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard).order_by("id")]
        self.assertEqual(len(active_tiles), new_count)
        for i, tile in enumerate(active_tiles):
            self.assertEqual(tile.insight_id, new_insights[i].id)

        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), initial_count + new_count)
        soft_deleted = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(soft_deleted), initial_count)

    async def test_is_dangerous_operation_with_insight_ids(self):
        """Test that providing insight_ids is flagged as a dangerous operation only when insights change."""
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Test Dashboard",
            created_by=self.user,
        )

        existing_insight = await self._create_insight("Existing Insight")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=existing_insight, layouts={})

        new_insight = await self._create_insight("New Insight")

        # Replacing with different insight should be dangerous
        tool1 = self._create_tool()
        action_with_different_insight = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
        )
        self.assertTrue(await tool1.is_dangerous_operation(action=action_with_different_insight))

        # Keeping same insight should NOT be dangerous
        tool2 = self._create_tool()
        action_with_same_insight = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[existing_insight.short_id],
        )
        self.assertFalse(await tool2.is_dangerous_operation(action=action_with_same_insight))

        # Just updating name/description should NOT be dangerous
        tool3 = self._create_tool()
        action_metadata = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            name="New Name",
            description="New description",
        )
        self.assertFalse(await tool3.is_dangerous_operation(action=action_metadata))

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
        # Use real context manager for this test since it needs to fetch from multiple sources
        context_manager = AssistantContextManager(team=self.team, user=self.user)
        tool = UpsertDashboardTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        # Test ordering: state, artifact, database
        insight_ids = [state_viz_id, artifact.short_id, db_insight.short_id]

        # First get the artifacts, then resolve them to insights
        artifacts = await tool._get_visualization_artifacts(insight_ids)
        insights = tool._resolve_insights(artifacts)

        self.assertEqual(len(insights), 3)

        # Verify order is preserved
        # State visualizations get default name "Insight" from the handler
        self.assertEqual(insights[0].name, "Insight")
        self.assertEqual(insights[1].name, "Artifact Insight")
        self.assertEqual(insights[2].name, "Database Insight")

    async def test_full_integration_positional_reordering(self):
        """
        Integration test: Verify dashboard update with reordering and new insights.

        Initial dashboard: [A, B, C] (each with specific layouts)
        Update with: [B, D, A, E]
        Expected:
        - Existing insights (B, A) keep their tiles with updated coordinates
        - C's tile is soft-deleted (not in new list)
        - New tiles created for D and E
        - Visual order is [B, D, A, E] based on insight_ids order
        """
        # Create initial dashboard with A, B, C
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard ABC",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")
        insight_c = await self._create_insight("Insight C")

        tile_a = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        )
        tile_b = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_b, layouts={"sm": {"x": 6, "y": 0, "w": 6, "h": 5}}
        )
        tile_c = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_c, layouts={"sm": {"x": 0, "y": 5, "w": 6, "h": 5}}
        )

        # Create new insights D and E
        insight_d = await self._create_insight("Insight D")
        insight_e = await self._create_insight("Insight E")

        # Update dashboard with new order: [B, D, A, E]
        tool = self._create_tool()
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_b.short_id, insight_d.short_id, insight_a.short_id, insight_e.short_id],
        )

        result, _ = await tool._arun_impl(action)

        # Verify the result contains all insights
        self.assertIn("Insight B", result)
        self.assertIn("Insight D", result)
        self.assertIn("Insight A", result)
        self.assertIn("Insight E", result)

        # Verify tiles in database have correct visual order [B, D, A, E]
        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 4)
        sorted_tiles = DashboardTile.sort_tiles_by_layout(active_tiles)

        # Verify visual order
        self.assertEqual(sorted_tiles[0].insight_id, insight_b.id)
        self.assertEqual(sorted_tiles[1].insight_id, insight_d.id)
        self.assertEqual(sorted_tiles[2].insight_id, insight_a.id)
        self.assertEqual(sorted_tiles[3].insight_id, insight_e.id)

        # Existing insights (A, B) keep their original tiles
        self.assertEqual(sorted_tiles[0].id, tile_b.id)  # B's tile
        self.assertEqual(sorted_tiles[2].id, tile_a.id)  # A's tile

        # C's tile should be soft-deleted
        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        # 3 original (A, B, C) + 2 new (D, E) = 5 total, with C soft-deleted
        self.assertEqual(len(all_tiles), 5)
        deleted_tiles = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(deleted_tiles), 1)
        self.assertEqual(deleted_tiles[0].id, tile_c.id)

    async def test_full_integration_with_empty_layouts(self):
        """
        Integration test: Verify ordering works even with empty layouts.

        When layouts are empty ({}), the tool should generate default sequential layouts
        to ensure proper ordering.
        """
        # Create initial dashboard with A, B, C (empty layouts)
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard ABC No Layouts",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")
        insight_c = await self._create_insight("Insight C")

        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_a, layouts={})
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_b, layouts={})
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight_c, layouts={})

        # Create new insights D and E
        insight_d = await self._create_insight("Insight D")
        insight_e = await self._create_insight("Insight E")

        # Update dashboard with new order: [B, D, A, E]
        tool = self._create_tool()
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_b.short_id, insight_d.short_id, insight_a.short_id, insight_e.short_id],
        )

        result, _ = await tool._arun_impl(action)

        # Verify the result contains all insights
        self.assertIn("Insight B", result)
        self.assertIn("Insight D", result)
        self.assertIn("Insight A", result)
        self.assertIn("Insight E", result)

        # Verify tiles have correct visual order [B, D, A, E]
        all_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 4)
        sorted_tiles = DashboardTile.sort_tiles_by_layout(all_tiles)

        # Verify order matches
        self.assertEqual(sorted_tiles[0].insight_id, insight_b.id)
        self.assertEqual(sorted_tiles[1].insight_id, insight_d.id)
        self.assertEqual(sorted_tiles[2].insight_id, insight_a.id)
        self.assertEqual(sorted_tiles[3].insight_id, insight_e.id)

        # Verify layouts were generated (not empty)
        for tile in sorted_tiles:
            self.assertIsNotNone(tile.layouts)
            self.assertIn("sm", tile.layouts)
            self.assertIn("y", tile.layouts["sm"])

    async def test_update_preserves_existing_insight_tiles(self):
        """
        Test that existing insights keep their original tiles with updated coordinates.

        When updating a dashboard:
        - Existing insights that remain keep their tile IDs
        - Their layouts are updated based on position in insight_ids
        - Sizes (w, h) are preserved, coordinates (x, y) are updated
        """
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Layouts",
            created_by=self.user,
        )

        insight_a = await self._create_insight("Insight A")
        insight_b = await self._create_insight("Insight B")

        # Create tiles with specific layouts
        tile_a = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts={"sm": {"x": 0, "y": 0, "w": 8, "h": 7}}, color="blue"
        )
        tile_b = await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_b, layouts={"sm": {"x": 0, "y": 7, "w": 10, "h": 6}}, color="white"
        )

        original_tile_a_id = tile_a.id
        original_tile_b_id = tile_b.id

        tool = self._create_tool()

        # Reorder: [B, A] - same insights, different order
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insight_b.short_id, insight_a.short_id],
        )

        await tool._arun_impl(action)

        # Fetch tiles after update
        await tile_a.arefresh_from_db()
        await tile_b.arefresh_from_db()

        # Tiles keep their IDs
        self.assertEqual(tile_a.id, original_tile_a_id)
        self.assertEqual(tile_b.id, original_tile_b_id)

        # Sizes are preserved
        self.assertEqual(tile_a.layouts["sm"]["w"], 8)
        self.assertEqual(tile_a.layouts["sm"]["h"], 7)
        self.assertEqual(tile_b.layouts["sm"]["w"], 10)
        self.assertEqual(tile_b.layouts["sm"]["h"], 6)

        # Coordinates are updated based on order
        # B (w=10, wide) at position 0: x=0, y=0
        # A (w=8, wide) at position 1: x=0, y=6 (below B which has h=6)
        self.assertEqual(tile_b.layouts["sm"]["x"], 0)
        self.assertEqual(tile_b.layouts["sm"]["y"], 0)
        self.assertEqual(tile_a.layouts["sm"]["x"], 0)
        self.assertEqual(tile_a.layouts["sm"]["y"], 6)

    async def test_two_column_flow_layout_algorithm(self):
        """
        Test the 2-column flow layout algorithm.

        Rules:
        - Half-width tiles (w<=6) flow left-to-right into 2 columns
        - Full-width tiles (w>6) span both columns
        - Tiles are placed in the column with lower Y (prefers left when equal)
        - Original widths and heights are preserved
        """
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard for Layout Test",
            created_by=self.user,
        )

        # Create insights with different widths:
        # A: w=6 (half), B: w=6 (half), C: w=12 (full), D: w=6 (half), E: w=6 (half)
        insight_a = await self._create_insight("A")
        insight_b = await self._create_insight("B")
        insight_c = await self._create_insight("C")
        insight_d = await self._create_insight("D")
        insight_e = await self._create_insight("E")

        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_a, layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_b, layouts={"sm": {"x": 6, "y": 0, "w": 6, "h": 4}}
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_c, layouts={"sm": {"x": 0, "y": 5, "w": 12, "h": 3}}
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_d, layouts={"sm": {"x": 0, "y": 8, "w": 6, "h": 5}}
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard, insight=insight_e, layouts={"sm": {"x": 6, "y": 8, "w": 6, "h": 6}}
        )

        tool = self._create_tool()

        # Reorder: [A, B, C, D, E] -> same order, should produce correct layout
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[
                insight_a.short_id,
                insight_b.short_id,
                insight_c.short_id,
                insight_d.short_id,
                insight_e.short_id,
            ],
        )

        await tool._arun_impl(action)

        # Fetch and sort tiles
        tiles = {
            t.insight_id: t async for t in DashboardTile.objects.filter(dashboard=dashboard).select_related("insight")
        }

        tile_a = tiles[insight_a.id]
        tile_b = tiles[insight_b.id]
        tile_c = tiles[insight_c.id]
        tile_d = tiles[insight_d.id]
        tile_e = tiles[insight_e.id]

        # Expected layout:
        # A (w=6, h=5): x=0, y=0 (left column, first)
        # B (w=6, h=4): x=6, y=0 (right column, left_y=5 > right_y=0, so goes right)
        # C (w=12, h=3): x=0, y=5 (full width, below max(5, 4)=5)
        # D (w=6, h=5): x=0, y=8 (left column, both at y=8 after C)
        # E (w=6, h=6): x=6, y=8 (right column)

        # Verify widths and heights preserved
        self.assertEqual(tile_a.layouts["sm"]["w"], 6)
        self.assertEqual(tile_a.layouts["sm"]["h"], 5)
        self.assertEqual(tile_b.layouts["sm"]["w"], 6)
        self.assertEqual(tile_b.layouts["sm"]["h"], 4)
        self.assertEqual(tile_c.layouts["sm"]["w"], 12)
        self.assertEqual(tile_c.layouts["sm"]["h"], 3)

        # Verify coordinates
        # A: first tile, goes to left column
        self.assertEqual(tile_a.layouts["sm"]["x"], 0)
        self.assertEqual(tile_a.layouts["sm"]["y"], 0)

        # B: second tile, left_y=5, right_y=0, goes to right column (lower Y)
        self.assertEqual(tile_b.layouts["sm"]["x"], 6)
        self.assertEqual(tile_b.layouts["sm"]["y"], 0)

        # C: wide tile (w=12), placed at y=max(5, 4)=5, advances both to y=8
        self.assertEqual(tile_c.layouts["sm"]["x"], 0)
        self.assertEqual(tile_c.layouts["sm"]["y"], 5)

        # D: after C, both columns at y=8, goes left (prefers left when equal)
        self.assertEqual(tile_d.layouts["sm"]["x"], 0)
        self.assertEqual(tile_d.layouts["sm"]["y"], 8)

        # E: left_y=13, right_y=8, goes to right column
        self.assertEqual(tile_e.layouts["sm"]["x"], 6)
        self.assertEqual(tile_e.layouts["sm"]["y"], 8)

    @parameterized.expand(
        [
            ("at_end", ["A", "C", "B"]),  # [A, B, C] -> [A, C] -> [A, C, B]
            ("at_beginning", ["B", "A", "C"]),  # [A, B, C] -> [A, C] -> [B, A, C]
        ]
    )
    async def test_restoring_previously_removed_insight(self, _name: str, new_order: list[str]):
        """When a previously removed insight is restored, the tile should be undeleted."""
        insights = {
            "A": await self._create_insight("Insight_A"),
            "B": await self._create_insight("Insight_B"),
            "C": await self._create_insight("Insight_C"),
        }
        dashboard = await Dashboard.objects.acreate(team=self.team, name="Dashboard", created_by=self.user)
        for i, key in enumerate(["A", "B", "C"]):
            await DashboardTile.objects.acreate(
                dashboard=dashboard, insight=insights[key], layouts={"sm": {"x": 0, "y": i * 5, "w": 12, "h": 5}}
            )

        # Simulate removing B (soft-delete its tile)
        tile_b = await DashboardTile.objects.aget(dashboard=dashboard, insight=insights["B"])
        tile_b.deleted = True
        await tile_b.asave()

        # Restore B at specified position
        tool = self._create_tool()
        action = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[insights[key].short_id for key in new_order],
        )
        result, _ = await tool._arun_impl(action)

        # Verify output order
        for i in range(len(new_order) - 1):
            self.assertLess(
                result.index(f"Insight_{new_order[i]}"),
                result.index(f"Insight_{new_order[i + 1]}"),
            )

        # B's tile should be undeleted
        await tile_b.arefresh_from_db()
        self.assertFalse(tile_b.deleted)

        # Dashboard should have 3 active tiles
        active_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(active_tiles), 3)
        self.assertEqual({t.insight_id for t in active_tiles}, {insights[k].id for k in ["A", "B", "C"]})


class TestGetDashboardAndSortedTiles(BaseTest):
    def _create_tool(self, state: AssistantState | None = None) -> UpsertDashboardTool:
        if state is None:
            state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = AssistantContextManager(team=self.team, user=self.user)
        return UpsertDashboardTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

    async def _create_insight(self, name: str) -> Insight:
        return await Insight.objects.acreate(
            team=self.team,
            created_by=self.user,
            name=name,
            query=InsightVizNode(source=DEFAULT_TRENDS_QUERY).model_dump(),
            saved=True,
        )

    async def test_returns_dashboard_and_sorted_tiles(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Test Dashboard",
            created_by=self.user,
        )

        insight1 = await self._create_insight("Top Left")
        insight2 = await self._create_insight("Top Right")
        insight3 = await self._create_insight("Bottom")

        await DashboardTile.objects.acreate(
            dashboard=dashboard,
            insight=insight2,
            layouts={"sm": {"x": 6, "y": 0, "w": 6, "h": 5}},
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard,
            insight=insight3,
            layouts={"sm": {"x": 0, "y": 5, "w": 12, "h": 5}},
        )
        await DashboardTile.objects.acreate(
            dashboard=dashboard,
            insight=insight1,
            layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}},
        )

        tool = self._create_tool()
        sorted_tiles = await tool._get_dashboard_sorted_tiles(dashboard)

        self.assertEqual(len(sorted_tiles), 3)
        self.assertEqual(sorted_tiles[0].insight_id, insight1.id)
        self.assertEqual(sorted_tiles[1].insight_id, insight2.id)
        self.assertEqual(sorted_tiles[2].insight_id, insight3.id)

    async def test_raises_error_for_nonexistent_dashboard(self):
        tool = self._create_tool()

        with self.assertRaises(MaxToolFatalError) as ctx:
            await tool._get_dashboard("999999")

        self.assertIn("999999", str(ctx.exception))

    async def test_raises_error_for_deleted_dashboard(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Deleted Dashboard",
            created_by=self.user,
            deleted=True,
        )

        tool = self._create_tool()

        with self.assertRaises(MaxToolFatalError) as ctx:
            await tool._get_dashboard(str(dashboard.id))

        self.assertIn(str(dashboard.id), str(ctx.exception))

    async def test_excludes_soft_deleted_tiles(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Dashboard with Deleted Tiles",
            created_by=self.user,
        )

        insight1 = await self._create_insight("Active")
        insight2 = await self._create_insight("Deleted")

        await DashboardTile.objects.acreate(
            dashboard=dashboard,
            insight=insight1,
            layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}},
        )
        await DashboardTile.objects_including_soft_deleted.acreate(
            dashboard=dashboard,
            insight=insight2,
            layouts={"sm": {"x": 6, "y": 0, "w": 6, "h": 5}},
            deleted=True,
        )

        tool = self._create_tool()
        sorted_tiles = await tool._get_dashboard_sorted_tiles(dashboard)

        self.assertEqual(len(sorted_tiles), 1)
        self.assertEqual(sorted_tiles[0].insight_id, insight1.id)

    async def test_returns_empty_tiles_for_dashboard_without_tiles(self):
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Empty Dashboard",
            created_by=self.user,
        )

        tool = self._create_tool()
        result_dashboard = await tool._get_dashboard(dashboard.id)
        sorted_tiles = await tool._get_dashboard_sorted_tiles(dashboard)

        self.assertEqual(result_dashboard.id, dashboard.id)
        self.assertEqual(len(sorted_tiles), 0)


class TestGetVisualizationArtifacts(BaseTest):
    def _create_tool(self, state: AssistantState | None = None) -> UpsertDashboardTool:
        if state is None:
            state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = AssistantContextManager(team=self.team, user=self.user)
        return UpsertDashboardTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

    async def _create_insight(self, name: str) -> Insight:
        return await Insight.objects.acreate(
            team=self.team,
            created_by=self.user,
            name=name,
            query=InsightVizNode(source=DEFAULT_TRENDS_QUERY).model_dump(),
            saved=True,
        )

    async def test_returns_artifacts_from_state_messages(self):
        viz_id = str(uuid4())
        viz_message = VisualizationMessage(
            id=viz_id,
            query="Show me pageviews",
            answer=DEFAULT_TRENDS_QUERY,
            plan="I'll create a trends chart",
        )
        state = AssistantState(messages=[viz_message], root_tool_call_id=str(uuid4()))

        tool = self._create_tool(state=state)

        results = await tool._get_visualization_artifacts([viz_id])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content.query, DEFAULT_TRENDS_QUERY)

    async def test_returns_artifacts_from_saved_insights(self):
        insight = await self._create_insight("Saved Insight")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        results = await tool._get_visualization_artifacts([insight.short_id])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content.name, "Saved Insight")

    async def test_returns_artifacts_from_database(self):
        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=conversation,
            name="DB Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={
                "query": DEFAULT_TRENDS_QUERY.model_dump(exclude_none=True),
                "name": "DB Artifact",
            },
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        results = await tool._get_visualization_artifacts([artifact.short_id])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content.name, "DB Artifact")

    async def test_preserves_order_with_mixed_sources(self):
        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        db_artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=conversation,
            name="DB Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={
                "query": DEFAULT_TRENDS_QUERY.model_dump(exclude_none=True),
                "name": "DB Artifact",
            },
        )

        insight = await self._create_insight("Insight Artifact")

        state_viz_id = str(uuid4())
        state_viz = VisualizationMessage(
            id=state_viz_id,
            query="state query",
            answer=DEFAULT_TRENDS_QUERY,
            plan="state plan",
        )

        state = AssistantState(messages=[state_viz], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        # Request in specific order: db, state, insight
        results = await tool._get_visualization_artifacts([db_artifact.short_id, state_viz_id, insight.short_id])

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].content.name, "DB Artifact")
        self.assertEqual(results[1].content.name, "Insight")
        self.assertEqual(results[2].content.name, "Insight Artifact")

    @parameterized.expand(
        [
            ("single_missing", [], ["nonexistent-id"]),
            ("multiple_missing_with_valid", ["Valid Insight"], ["missing-1", "missing-2"]),
        ]
    )
    async def test_raises_error_when_artifacts_not_found(
        self, _name: str, valid_insight_names: list[str], missing_ids: list[str]
    ):
        valid_insights = [await self._create_insight(name) for name in valid_insight_names]
        insight_ids = [i.short_id for i in valid_insights] + missing_ids

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._get_visualization_artifacts(insight_ids)

        for missing_id in missing_ids:
            self.assertIn(missing_id, str(ctx.exception))


class TestGetUpdateDiff(BaseTest):
    def _create_tool(self, state: AssistantState | None = None) -> UpsertDashboardTool:
        if state is None:
            state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = AssistantContextManager(team=self.team, user=self.user)
        return UpsertDashboardTool(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

    async def _create_insight(self, name: str) -> Insight:
        return await Insight.objects.acreate(
            team=self.team,
            created_by=self.user,
            name=name,
            query=InsightVizNode(source=DEFAULT_TRENDS_QUERY).model_dump(),
            saved=True,
        )

    async def _create_dashboard_with_tiles(
        self, name: str, insights: list[Insight]
    ) -> tuple[Dashboard, list[DashboardTile]]:
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name=name,
            created_by=self.user,
        )
        tiles = []
        for i, insight in enumerate(insights):
            tile = await DashboardTile.objects.acreate(
                dashboard=dashboard,
                insight=insight,
                layouts={"sm": {"x": 0, "y": i * 5, "w": 12, "h": 5}},
            )
            tiles.append(tile)
        return dashboard, DashboardTile.sort_tiles_by_layout(tiles)

    async def test_returns_empty_diff_for_empty_insight_ids(self):
        insight = await self._create_insight("Existing")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight])

        tool = self._create_tool()
        diff = await tool._get_update_diff(tiles, [])

        self.assertEqual(diff["created"], [])
        self.assertEqual(diff["deleted"], [])

    async def test_identifies_deleted_tiles(self):
        insight1 = await self._create_insight("Will Delete 1")
        insight2 = await self._create_insight("Will Delete 2")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight1, insight2])

        # Create a new insight - both existing ones will be deleted
        new_insight = await self._create_insight("New")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [new_insight.short_id])

        # Both existing insights are deleted (not in new list)
        self.assertEqual(len(diff["deleted"]), 2)
        deleted_ids = {tile.insight_id for tile in diff["deleted"]}
        self.assertEqual(deleted_ids, {insight1.id, insight2.id})
        # New insight is created
        self.assertEqual(len(diff["created"]), 1)

    async def test_identifies_created_tiles(self):
        """When keeping an existing insight and adding new ones, only the new ones are "created"."""
        insight = await self._create_insight("Existing")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight])

        # Create new insights to add
        new_insight1 = await self._create_insight("New 1")
        new_insight2 = await self._create_insight("New 2")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        # Keep existing insight at position 0, add new ones
        diff = await tool._get_update_diff(tiles, [insight.short_id, new_insight1.short_id, new_insight2.short_id])

        # "created" only includes insights not already in the dashboard
        self.assertEqual(len(diff["created"]), 2)
        created_names = {a.content.name for a in diff["created"]}
        self.assertEqual(created_names, {"New 1", "New 2"})
        self.assertEqual(len(diff["deleted"]), 0)

    async def test_identifies_swapped_insight(self):
        """When replacing one insight with another, old is deleted and new is created."""
        old_insight = await self._create_insight("Old")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [old_insight])

        new_insight = await self._create_insight("New")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [new_insight.short_id])

        self.assertEqual(len(diff["deleted"]), 1)
        self.assertEqual(diff["deleted"][0].insight_id, old_insight.id)
        self.assertEqual(len(diff["created"]), 1)
        self.assertEqual(diff["created"][0].content.name, "New")

    async def test_handles_complex_diff(self):
        """
        Initial: [A, B, C] (3 tiles)
        New: [D, E, F, G] (4 insights)
        Result:
        - deleted: A, B, C (all removed from dashboard)
        - created: D, E, F, G (all new to dashboard)
        """
        insight_a = await self._create_insight("A")
        insight_b = await self._create_insight("B")
        insight_c = await self._create_insight("C")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight_a, insight_b, insight_c])

        insight_d = await self._create_insight("D")
        insight_e = await self._create_insight("E")
        insight_f = await self._create_insight("F")
        insight_g = await self._create_insight("G")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(
            tiles, [insight_d.short_id, insight_e.short_id, insight_f.short_id, insight_g.short_id]
        )

        self.assertEqual(len(diff["deleted"]), 3)
        deleted_ids = {tile.insight_id for tile in diff["deleted"]}
        self.assertEqual(deleted_ids, {insight_a.id, insight_b.id, insight_c.id})
        self.assertEqual(len(diff["created"]), 4)
        created_names = {a.content.name for a in diff["created"]}
        self.assertEqual(created_names, {"D", "E", "F", "G"})

    async def test_handles_shrinking_diff(self):
        """
        Initial: [A, B, C] (3 tiles)
        New: [D] (1 insight)
        Result:
        - deleted: A, B, C (all removed)
        - created: D (new to dashboard)
        """
        insight_a = await self._create_insight("A")
        insight_b = await self._create_insight("B")
        insight_c = await self._create_insight("C")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight_a, insight_b, insight_c])

        insight_d = await self._create_insight("D")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [insight_d.short_id])

        self.assertEqual(len(diff["deleted"]), 3)
        deleted_insight_ids = {tile.insight_id for tile in diff["deleted"]}
        self.assertEqual(deleted_insight_ids, {insight_a.id, insight_b.id, insight_c.id})
        self.assertEqual(len(diff["created"]), 1)
        self.assertEqual(diff["created"][0].content.name, "D")

    async def test_caches_update_diff(self):
        insight = await self._create_insight("Existing")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight])

        new_insight = await self._create_insight("New")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff1 = await tool._get_update_diff(tiles, [new_insight.short_id])
        diff2 = await tool._get_update_diff(tiles, [new_insight.short_id])

        self.assertIs(diff1, diff2)

    async def test_handles_empty_dashboard(self):
        await Dashboard.objects.acreate(
            team=self.team,
            name="Empty Dashboard",
            created_by=self.user,
        )
        tiles: list[DashboardTile] = []

        new_insight = await self._create_insight("New")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [new_insight.short_id])

        self.assertEqual(len(diff["created"]), 1)
        self.assertEqual(diff["created"][0].content.name, "New")
        self.assertEqual(len(diff["deleted"]), 0)

    async def test_recognizes_same_insight_in_position(self):
        """When an insight ID is already in the dashboard, no changes are needed."""
        insight = await self._create_insight("Same")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight])

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [insight.short_id])

        # No changes needed - insight stays in place
        self.assertEqual(len(diff["created"]), 0)
        self.assertEqual(len(diff["deleted"]), 0)
