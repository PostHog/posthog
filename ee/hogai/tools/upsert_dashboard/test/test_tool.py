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

    async def test_update_nonexistent_dashboard_returns_error(self):
        tool = self._create_tool()

        action = UpdateDashboardToolArgs(
            dashboard_id="99999999",
            insight_ids=["some-id"],
        )

        with self.assertRaises(MaxToolFatalError) as ctx:
            await tool._arun_impl(action)

        self.assertIn("99999999", str(ctx.exception))

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

        with self.assertRaises(MaxToolFatalError) as ctx:
            await tool._arun_impl(action)

        self.assertIn(str(dashboard.id), str(ctx.exception))

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

    async def test_is_dangerous_operation_with_insight_ids(self):
        """Test that providing insight_ids is flagged as a dangerous operation."""
        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Test Dashboard",
            created_by=self.user,
        )

        existing_insight = await self._create_insight("Existing Insight")
        await DashboardTile.objects.acreate(dashboard=dashboard, insight=existing_insight, layouts={})

        new_insight = await self._create_insight("New Insight")

        tool = self._create_tool()

        # insight_ids should be dangerous (since it replaces)
        action_with_insights = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            insight_ids=[new_insight.short_id],
        )
        self.assertTrue(await tool.is_dangerous_operation(action=action_with_insights))

        # Just updating name/description should NOT be dangerous
        action_metadata = UpdateDashboardToolArgs(
            dashboard_id=str(dashboard.id),
            name="New Name",
            description="New description",
        )
        self.assertFalse(await tool.is_dangerous_operation(action=action_metadata))

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
        Integration test: Verify that dashboard update preserves visual order via layout swapping.

        Initial dashboard: [A, B, C] (each with specific layouts)
        Update with: [B, D, A, E]
        Expected visual result: [B, D, A, E] (determined by layout positions)

        Implementation details:
        - Existing insights (B, A) keep their tile IDs but get new layout positions
        - New insight D reuses tile from removed insight C
        - New insight E gets a new tile
        - Visual order is determined by layout (x, y) coordinates
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

        # Store original tile IDs to verify they're reused
        original_tile_ids = {tile_a.id, tile_b.id, tile_c.id}

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
        # We use layout sorting to determine visual position
        all_tiles = [t async for t in DashboardTile.objects.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 4)
        sorted_tiles = DashboardTile.sort_tiles_by_layout(all_tiles)

        # Position 0: B (moved via layout swap)
        self.assertEqual(sorted_tiles[0].insight_id, insight_b.id)
        self.assertIn(sorted_tiles[0].id, original_tile_ids)

        # Position 1: D (assigned to freed tile)
        self.assertEqual(sorted_tiles[1].insight_id, insight_d.id)
        self.assertIn(sorted_tiles[1].id, original_tile_ids)

        # Position 2: A (moved via layout swap)
        self.assertEqual(sorted_tiles[2].insight_id, insight_a.id)
        self.assertIn(sorted_tiles[2].id, original_tile_ids)

        # Position 3: E (new tile created)
        self.assertEqual(sorted_tiles[3].insight_id, insight_e.id)
        self.assertNotIn(sorted_tiles[3].id, original_tile_ids)

        # Verify no tiles were soft-deleted (all were reused)
        all_tiles = [t async for t in DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard)]
        self.assertEqual(len(all_tiles), 4)
        deleted_tiles = [t for t in all_tiles if t.deleted]
        self.assertEqual(len(deleted_tiles), 0)

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

    async def test_raises_error_when_artifact_not_found(self):
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._get_visualization_artifacts(["nonexistent-id"])

        self.assertIn("nonexistent-id", str(ctx.exception))

    async def test_raises_error_when_some_artifacts_not_found(self):
        insight = await self._create_insight("Valid Insight")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._get_visualization_artifacts([insight.short_id, "missing-1", "missing-2"])

        self.assertIn("missing-1", str(ctx.exception))
        self.assertIn("missing-2", str(ctx.exception))


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
        self.assertEqual(diff["replaced"], [])

    async def test_identifies_deleted_tiles(self):
        insight1 = await self._create_insight("Will Keep")
        insight2 = await self._create_insight("Will Delete")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight1, insight2])

        # Create a new insight to replace the first one
        new_insight = await self._create_insight("Replacement")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [new_insight.short_id])

        self.assertEqual(len(diff["deleted"]), 1)
        self.assertEqual(diff["deleted"][0].insight_id, insight2.id)
        self.assertEqual(len(diff["replaced"]), 1)
        self.assertEqual(diff["replaced"][0][0].insight_id, insight1.id)

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
        self.assertEqual(diff["created"][0].content.name, "New 1")
        self.assertEqual(diff["created"][1].content.name, "New 2")
        self.assertEqual(len(diff["deleted"]), 0)
        # The existing insight at position 0 is "replaced" with itself
        self.assertEqual(len(diff["replaced"]), 1)

    async def test_identifies_replaced_tiles(self):
        old_insight = await self._create_insight("Old")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [old_insight])

        new_insight = await self._create_insight("New")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [new_insight.short_id])

        self.assertEqual(len(diff["replaced"]), 1)
        tile, artifact = diff["replaced"][0]
        self.assertEqual(tile.insight_id, old_insight.id)
        self.assertEqual(artifact.content.name, "New")
        self.assertEqual(len(diff["deleted"]), 0)
        # "created" should be empty since the new insight is used for positional replacement
        self.assertEqual(len(diff["created"]), 0)

    async def test_handles_complex_diff(self):
        """
        Initial: [A, B, C] (3 tiles)
        New: [D, E, F, G] (4 insights)
        Result:
        - replaced: A->D, B->E, C->F (3 position replacements)
        - created: G (only G needs a new tile, D/E/F reuse existing tiles)
        - deleted: none
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

        self.assertEqual(len(diff["replaced"]), 3)
        # "created" only includes insights that need new tiles (not used for replacement)
        self.assertEqual(len(diff["created"]), 1)
        self.assertEqual(diff["created"][0].content.name, "G")
        self.assertEqual(len(diff["deleted"]), 0)

    async def test_handles_shrinking_diff(self):
        """
        Initial: [A, B, C] (3 tiles)
        New: [D] (1 insight)
        Result:
        - replaced: A->D (1 position replacement)
        - deleted: B, C (tiles with no corresponding new insight)
        - created: empty (D is used for positional replacement, not a new tile)
        """
        insight_a = await self._create_insight("A")
        insight_b = await self._create_insight("B")
        insight_c = await self._create_insight("C")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight_a, insight_b, insight_c])

        insight_d = await self._create_insight("D")

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [insight_d.short_id])

        self.assertEqual(len(diff["replaced"]), 1)
        self.assertEqual(diff["replaced"][0][1].content.name, "D")
        self.assertEqual(len(diff["deleted"]), 2)
        deleted_insight_ids = {tile.insight_id for tile in diff["deleted"]}
        self.assertEqual(deleted_insight_ids, {insight_b.id, insight_c.id})
        # "created" is empty because D is used for positional replacement
        self.assertEqual(len(diff["created"]), 0)

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
        self.assertEqual(len(diff["replaced"]), 0)

    async def test_recognizes_same_insight_in_position(self):
        """When an insight ID is already in the dashboard at the same position, it should still be treated as a replacement."""
        insight = await self._create_insight("Same")
        _, tiles = await self._create_dashboard_with_tiles("Dashboard", [insight])

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        tool = self._create_tool(state=state)

        diff = await tool._get_update_diff(tiles, [insight.short_id])

        # The insight is replaced with itself
        self.assertEqual(len(diff["replaced"]), 1)
        self.assertEqual(diff["replaced"][0][0].insight_id, insight.id)
        self.assertEqual(len(diff["created"]), 0)
        self.assertEqual(len(diff["deleted"]), 0)
