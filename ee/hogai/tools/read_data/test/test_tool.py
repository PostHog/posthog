from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import (
    ArtifactSource,
    AssistantToolCallMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    VisualizationArtifactContent,
)

from posthog.models import Dashboard, DashboardTile, Insight

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseSavedQuery, DataWarehouseTable

from ee.hogai.artifacts.types import StateArtifactResult
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.read_data.tool import ReadDataTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage, NodePath


class TestReadDataTool(BaseTest):
    async def test_create_tool_class_with_billing_access(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=True)

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        # Description should include billing prompt
        assert "billing_info" in tool.description
        assert "Billing information" in tool.description

    async def test_create_tool_class_without_billing_access(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        # Description should NOT include billing prompt
        assert "billing_info" not in tool.description
        assert "Billing information" not in tool.description
        assert "data_warehouse_schema" in tool.description
        assert "data_warehouse_table" in tool.description

    async def test_create_tool_class_without_context_manager(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))

        with patch("ee.hogai.tools.read_data.tool.AssistantContextManager") as mock_context_class:
            mock_context = MagicMock()
            mock_context.check_user_has_billing_access = AsyncMock(return_value=False)
            mock_context_class.return_value = mock_context

            tool = await ReadDataTool.create_tool_class(
                team=team,
                user=user,
                state=state,
            )

            mock_context_class.assert_called_once()
            assert tool is not None

    async def test_read_insight_schema_only(self):
        """Test reading an insight without executing it returns the schema."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        mock_query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        mock_content = VisualizationArtifactContent(
            name="Test Insight",
            description="A test description",
            query=mock_query,
        )

        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_visualization = AsyncMock(
            return_value=StateArtifactResult(content=mock_content, source=ArtifactSource.STATE)
        )

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123", "execute": False})

        assert "Test Insight" in result
        assert "abc123" in result
        assert "A test description" in result
        assert "TrendsQuery" in result
        assert artifact is None

    async def test_read_insight_with_execution(self):
        """Test reading an insight with execution returns results and artifact."""
        team = MagicMock()
        user = MagicMock()
        tool_call_id = "test_call_id"
        state = AssistantState(messages=[], root_tool_call_id=tool_call_id)
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        mock_query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        mock_content = VisualizationArtifactContent(
            name="Test Insight",
            description="A test description",
            query=mock_query,
        )

        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_visualization = AsyncMock(
            return_value=StateArtifactResult(content=mock_content, source=ArtifactSource.STATE)
        )

        with patch(
            "ee.hogai.context.insight.context.execute_and_format_query",
            new=AsyncMock(return_value="Formatted results"),
        ):
            tool = ReadDataTool(
                team=team,
                user=user,
                state=state,
                context_manager=context_manager,
                node_path=(NodePath(name="test_node", tool_call_id=tool_call_id, message_id="test"),),
            )

            result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123", "execute": True})

            # When execute=True, returns empty string and artifact
            assert result == ""
            assert artifact is not None
            assert len(artifact.messages) == 2

            # First message is ArtifactRefMessage
            artifact_ref = artifact.messages[0]
            assert isinstance(artifact_ref, ArtifactRefMessage)
            assert artifact_ref.artifact_id == "abc123"
            assert artifact_ref.source == ArtifactSource.STATE

            # Second message is the tool call message with results
            tool_call_msg = artifact.messages[1]
            assert isinstance(tool_call_msg, AssistantToolCallMessage)
            assert tool_call_msg.content is not None
            assert "Test Insight" in tool_call_msg.content
            assert "Formatted results" in tool_call_msg.content

    async def test_read_insight_not_found(self):
        """Test that not found insight raises MaxToolRetryableError."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_visualization = AsyncMock(return_value=None)

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        with pytest.raises(MaxToolRetryableError) as exc_info:
            await tool._arun_impl({"kind": "insight", "insight_id": "nonexistent", "execute": False})

        assert "nonexistent" in str(exc_info.value)

    async def test_read_insight_default_execute_is_false(self):
        """Test that execute defaults to False when not specified."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_insight = AsyncMock(return_value=None)

        mock_query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        mock_content = VisualizationArtifactContent(
            name="Test Insight",
            description=None,
            query=mock_query,
        )

        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_visualization = AsyncMock(
            return_value=StateArtifactResult(content=mock_content, source=ArtifactSource.STATE)
        )

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        # Don't pass execute, it should default to False and return schema only
        result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123"})

        assert artifact is None
        assert "Test Insight" in result
        assert "Query schema" in result

    async def test_read_insight_uses_fallback_name_when_none(self):
        """Test that insight name falls back to 'Insight {id}' when name is None."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        mock_query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        mock_content = VisualizationArtifactContent(
            name=None,
            description=None,
            query=mock_query,
        )

        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_visualization = AsyncMock(
            return_value=StateArtifactResult(content=mock_content, source=ArtifactSource.STATE)
        )

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123", "execute": False})

        assert "Insight abc123" in result

    async def test_read_dashboard_schema_only(self):
        """Test reading a dashboard without executing it returns the schema."""

        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Test Dashboard",
            description="A test dashboard description",
        )

        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl(
            {"kind": "dashboard", "dashboard_id": str(dashboard.id), "execute": False}
        )

        assert "Test Dashboard" in result
        assert str(dashboard.id) in result
        assert "A test dashboard description" in result
        assert artifact is None

    async def test_read_dashboard_includes_insight_short_id_and_db_id(self):
        """Test that dashboard insights include short_id and db_id fields."""

        dashboard = await Dashboard.objects.acreate(
            team=self.team,
            name="Test Dashboard",
        )

        insight = await Insight.objects.acreate(
            team=self.team,
            name="Test Insight",
            description="Test description",
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "name": "$pageview"}],
            },
        )

        await DashboardTile.objects.acreate(
            dashboard=dashboard,
            insight=insight,
        )

        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        with patch("ee.hogai.tools.read_data.tool.DashboardContext") as MockDashboardContext:
            mock_instance = MagicMock()
            mock_instance.format_schema = AsyncMock(return_value="Formatted schema")
            MockDashboardContext.return_value = mock_instance

            tool = await ReadDataTool.create_tool_class(
                team=self.team,
                user=user,
                state=state,
                context_manager=context_manager,
            )

            await tool._arun_impl(
                {
                    "kind": "dashboard",
                    "dashboard_id": str(dashboard.id),
                    "execute": False,
                }
            )

            # Verify DashboardContext was instantiated with correct arguments
            MockDashboardContext.assert_called_once()
            call_kwargs = MockDashboardContext.call_args.kwargs

            # Verify insights_data contains correct short_id and db_id
            insights_data = call_kwargs["insights_data"]
            assert len(insights_data) == 1
            insight_ctx = insights_data[0]

            assert insight_ctx.short_id == insight.short_id
            assert insight_ctx.db_id == insight.id

    async def test_list_tables_returns_core_tables_with_schema(self):
        """Test that data_warehouse_schema returns core PostHog tables with their field schemas."""
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl({"kind": "data_warehouse_schema"})

        assert "# Core PostHog tables" in result
        assert "## Table `events`" in result
        assert "- event (string)" in result
        assert "- timestamp (datetime)" in result
        assert "## Table `persons`" in result
        assert "## Table `sessions`" in result
        assert "## Table `groups`" in result
        assert artifact is None

    async def test_list_tables_includes_warehouse_tables(self):
        """Test that data_warehouse_schema includes warehouse table names."""
        credential = await DataWarehouseCredential.objects.acreate(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        await DataWarehouseTable.objects.acreate(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "id": {
                    "hogql": "StringDatabaseField",
                    "clickhouse": "Nullable(String)",
                    "schema_valid": True,
                }
            },
        )
        await DataWarehouseTable.objects.acreate(
            name="hubspot_contacts",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "email": {
                    "hogql": "StringDatabaseField",
                    "clickhouse": "Nullable(String)",
                    "schema_valid": True,
                }
            },
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_schema"})

        assert "# Data warehouse tables" in result
        assert "- hubspot_contacts" in result
        assert "- stripe_customers" in result
        assert "Use the `read_data` tool with the `data_warehouse_table` kind" in result

    async def test_list_tables_includes_views(self):
        """Test that data_warehouse_schema includes view names."""
        await DataWarehouseSavedQuery.objects.acreate(
            team=self.team,
            name="my_custom_view",
            query={"kind": "HogQLQuery", "query": "SELECT event FROM events LIMIT 100"},
        )
        await DataWarehouseSavedQuery.objects.acreate(
            team=self.team,
            name="revenue_summary",
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() as total FROM events",
            },
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_schema"})

        assert "# Data warehouse views" in result
        assert "- my_custom_view" in result
        assert "- revenue_summary" in result

    async def test_list_tables_omits_empty_warehouse_and_views_sections(self):
        """Test that data_warehouse_schema omits warehouse/views sections when empty."""
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_schema"})

        assert "# Data warehouse tables" not in result
        assert "# Views" not in result

    async def test_table_schema_returns_warehouse_table_fields(self):
        """Test that data_warehouse_table returns full schema for a warehouse table."""
        credential = await DataWarehouseCredential.objects.acreate(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        await DataWarehouseTable.objects.acreate(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "customer_id": {
                    "hogql": "StringDatabaseField",
                    "clickhouse": "Nullable(String)",
                    "schema_valid": True,
                },
                "email": {
                    "hogql": "StringDatabaseField",
                    "clickhouse": "Nullable(String)",
                    "schema_valid": True,
                },
                "created_at": {
                    "hogql": "DateTimeDatabaseField",
                    "clickhouse": "Nullable(DateTime64(3))",
                    "schema_valid": True,
                },
            },
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl({"kind": "data_warehouse_table", "table_name": "stripe_customers"})

        assert "Table `stripe_customers` with fields:" in result
        assert "- customer_id (string)" in result
        assert "- email (string)" in result
        assert "- created_at (datetime)" in result
        assert artifact is None

    async def test_table_schema_returns_view_fields(self):
        """Test that data_warehouse_table returns full schema for a view."""
        await DataWarehouseSavedQuery.objects.acreate(
            team=self.team,
            name="revenue_summary",
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() as total_count, event FROM events GROUP BY event",
            },
            columns={
                "total_count": {
                    "hogql": "IntegerDatabaseField",
                    "clickhouse": "UInt64",
                    "valid": True,
                },
                "event": {
                    "hogql": "StringDatabaseField",
                    "clickhouse": "String",
                    "valid": True,
                },
            },
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_table", "table_name": "revenue_summary"})

        assert "Table `revenue_summary` with fields:" in result
        assert "- total_count (integer)" in result
        assert "- event (string)" in result

    async def test_table_schema_returns_posthog_table_fields(self):
        """Test that data_warehouse_table returns schema for core PostHog tables."""
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_table", "table_name": "events"})

        assert "Table `events` with fields:" in result
        assert "- event (string)" in result
        assert "- timestamp (datetime)" in result

    async def test_table_schema_returns_error_when_table_not_found(self):
        """Test that data_warehouse_table returns an error message for unknown tables."""
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = await ReadDataTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "data_warehouse_table", "table_name": "nonexistent_table"})

        assert "Table `nonexistent_table` not found" in result
        assert "Available tables include:" in result
