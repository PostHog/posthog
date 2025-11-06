import pytest
from unittest.mock import AsyncMock, Mock, patch

from posthog.schema import AssistantToolCallMessage

from posthog.models import Dashboard

from products.dashboards.backend.max_tools import EditCurrentDashboardTool
from products.enterprise.backend.hogai.graph.dashboards.nodes import DashboardCreationNode
from products.enterprise.backend.hogai.utils.types.base import InsightQuery


class TestEditCurrentDashboardTool:
    """Test the EditCurrentDashboardTool with mocked dependencies"""

    async def mock_check_permissions(self, dashboard):
        """Mock permission check that always returns True"""
        return True

    def _setup_tool(self, context=None, team=None, user=None):
        """Helper to create an EditCurrentDashboardTool instance with context"""
        mock_team = team or Mock()
        mock_user = user or Mock()
        configurable = {"team": mock_team, "user": mock_user}
        if context:
            configurable["contextual_tools"] = {"edit_current_dashboard": context}
        tool = EditCurrentDashboardTool(team=mock_team, user=mock_user, config={"configurable": configurable})
        return tool

    @pytest.mark.asyncio
    async def test_arun_impl_missing_context(self):
        """Test _arun_impl fails when current_dashboard context is missing"""
        tool = self._setup_tool()

        with pytest.raises(ValueError, match="Context `current_dashboard` is required"):
            await tool._arun_impl()

    @pytest.mark.asyncio
    async def test_arun_impl_missing_dashboard_id(self):
        """Test _arun_impl fails when dashboard ID is missing from context"""
        tool = self._setup_tool({"current_dashboard": {}})

        with pytest.raises(ValueError, match="Dashboard ID not found in context"):
            await tool._arun_impl()

    @pytest.mark.asyncio
    async def test_arun_impl_dashboard_not_found(self):
        """Test _arun_impl handles dashboard not found gracefully"""
        tool = self._setup_tool({"current_dashboard": {"id": 99999}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.side_effect = Dashboard.DoesNotExist("Dashboard not found")

            content, _ = await tool._arun_impl()

            assert content == "Dashboard was not found."

    @pytest.mark.asyncio
    async def test_arun_impl_rename_dashboard_success(self):
        """Test successful dashboard renaming"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123
        mock_dashboard.name = "Original Name"

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)

            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                # Mock the handler method to avoid database access
                with patch.object(
                    tool,
                    "_handle_dashboard_name_update",
                    return_value="Dashboard was renamed to New Name successfully.",
                ):
                    content, _ = await tool._arun_impl(dashboard_name="New Name")

                    assert "Dashboard was renamed to New Name successfully." in content

    @pytest.mark.asyncio
    async def test_arun_impl_update_description_success(self):
        """Test successful dashboard description update"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123
        mock_dashboard.description = "Original description"

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)
            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                # Mock the handler method to avoid database access
                with patch.object(
                    tool,
                    "_handle_dashboard_description_update",
                    return_value="Dashboard description was updated successfully.",
                ):
                    content, _ = await tool._arun_impl(dashboard_description="New description")

                    assert "Dashboard description was updated successfully." in content

    @pytest.mark.asyncio
    async def test_arun_impl_add_insights_success(self):
        """Test successful insights addition"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123

        insights_to_add = [
            InsightQuery(name="Test Insight 1", description="First test insight"),
            InsightQuery(name="Test Insight 2", description="Second test insight"),
        ]

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with (
            patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db,
            patch.object(DashboardCreationNode, "arun") as mock_arun,
        ):
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)
            mock_result = Mock()
            mock_message = AssistantToolCallMessage(content="Insights added successfully", tool_call_id="test-id")
            mock_result.messages = [mock_message]
            mock_arun.return_value = mock_result

            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                content, _ = await tool._arun_impl(insights_to_add=insights_to_add)

                assert "Insights added successfully" in content

                assert tool._state.search_insights_queries == insights_to_add
                assert tool._state.dashboard_id == 123

    @pytest.mark.asyncio
    async def test_arun_impl_multiple_operations(self):
        """Test performing multiple operations in one call"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123
        mock_dashboard.name = "Original Name"
        mock_dashboard.description = "Original description"

        insights_to_add = [InsightQuery(name="Test Insight", description="Test description")]

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with (
            patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db,
            patch.object(DashboardCreationNode, "arun") as mock_arun,
        ):
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)
            mock_result = Mock()
            mock_message = AssistantToolCallMessage(content="Insights added", tool_call_id="test-id")
            mock_result.messages = [mock_message]
            mock_arun.return_value = mock_result

            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                with (
                    patch.object(
                        tool,
                        "_handle_dashboard_name_update",
                        return_value="Dashboard was renamed to New Name successfully.",
                    ),
                    patch.object(
                        tool,
                        "_handle_dashboard_description_update",
                        return_value="Dashboard description was updated successfully.",
                    ),
                ):
                    content, artifact = await tool._arun_impl(
                        dashboard_name="New Name",
                        dashboard_description="New description",
                        insights_to_add=insights_to_add,
                    )

                    # Should contain messages for all operations
                    assert "Dashboard was renamed to New Name successfully." in content
                    assert "Dashboard description was updated successfully." in content
                    assert "Insights added" in content
                    assert artifact is None

    @pytest.mark.asyncio
    async def test_handle_dashboard_name_update_exception(self):
        """Test dashboard name update handles exceptions gracefully"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)

            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                with patch.object(tool, "_update_dashboard_name", side_effect=Exception("Database error")):
                    content, _ = await tool._arun_impl(dashboard_name="New Name")

                    assert "Dashboard was not renamed to New Name." in content

    @pytest.mark.asyncio
    async def test_handle_dashboard_description_update_exception(self):
        """Test dashboard description update handles exceptions gracefully"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)

            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                with patch.object(tool, "_update_dashboard_description", side_effect=Exception("Database error")):
                    content, _ = await tool._arun_impl(dashboard_description="New description")

                    assert "Dashboard description was not updated." in content

    @pytest.mark.asyncio
    async def test_handle_insights_addition_exception(self):
        """Test insights addition handles exceptions gracefully"""
        mock_dashboard = Mock()
        mock_dashboard.id = 123

        insights_to_add = [InsightQuery(name="Test Insight", description="Test description")]

        tool = self._setup_tool({"current_dashboard": {"id": 123}})

        with patch("products.dashboards.backend.max_tools.database_sync_to_async") as mock_db:
            mock_db.return_value = AsyncMock(return_value=mock_dashboard)

            # Mock the permission check to return True
            with patch.object(
                EditCurrentDashboardTool, "_check_user_permissions", side_effect=self.mock_check_permissions
            ):
                with patch.object(DashboardCreationNode, "arun", side_effect=Exception("Creation failed")):
                    content, _ = await tool._arun_impl(insights_to_add=insights_to_add)

                    assert "Failed to add the insights to the dashboard." in content

    @pytest.mark.asyncio
    async def test_check_user_permissions_legacy(self):
        """Test check_user_permissions handles legacy permissions correctly"""
        mock_dashboard = Mock()
        mock_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT

        tool = self._setup_tool()

        # Mock the UserPermissions system to return False for can_edit
        with patch("products.dashboards.backend.max_tools.UserPermissions") as mock_user_perms:
            mock_perms_instance = Mock()
            mock_perms_instance.dashboard.return_value.can_edit = False
            mock_user_perms.return_value = mock_perms_instance

            result = await tool._check_user_permissions(mock_dashboard)
            assert result is False

    @pytest.mark.asyncio
    async def test_check_user_permissions_new_rbac(self):
        """Test check_user_permissions handles new RBAC system correctly"""
        mock_dashboard = Mock()
        # Don't set restriction_level to test the new RBAC path

        tool = self._setup_tool()

        # Mock the UserAccessControl system to return True
        with patch("products.dashboards.backend.max_tools.UserAccessControl") as mock_access_control:
            mock_access_instance = Mock()
            mock_access_instance.get_user_access_level.return_value = "editor"
            mock_access_control.return_value = mock_access_instance

            with patch("products.dashboards.backend.max_tools.access_level_satisfied_for_resource", return_value=True):
                # Mock the restriction_level comparison to avoid the TypeError
                with patch.object(
                    mock_dashboard, "restriction_level", Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
                ):
                    result = await tool._check_user_permissions(mock_dashboard)
                    assert result is True
