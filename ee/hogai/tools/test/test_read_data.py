from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import ArtifactMessage, ArtifactSource, AssistantTrendsQuery, VisualizationArtifactContent

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.read_data import ReadDataTool
from ee.hogai.utils.types import AssistantState


class TestReadDataTool(BaseTest):
    async def test_create_tool_class_with_billing_access(self):
        """Test that billing prompt is included when user has billing access."""
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
        """Test that billing prompt is excluded when user lacks billing access."""
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

        # Should still have base prompt content
        assert "data warehouse" in tool.description

    async def test_create_tool_class_without_context_manager(self):
        """Test that create_tool_class creates context manager if not provided."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))

        with patch("ee.hogai.tools.read_data.AssistantContextManager") as mock_context_class:
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

    async def test_arun_impl_artifacts_returns_formatted_artifacts(self):
        """Test that artifacts kind returns formatted artifact data."""
        team = MagicMock()
        user = MagicMock()

        viz_content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test Chart",
            description="A test visualization",
        )
        artifact_message = ArtifactMessage(
            id=str(uuid4()),
            artifact_id="artifact-123",
            source=ArtifactSource.ARTIFACT,
            content=viz_content,
        )

        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_conversation_artifact_messages = AsyncMock(return_value=[artifact_message])

        tool = ReadDataTool(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "artifacts"})

        context_manager.artifacts.aget_conversation_artifact_messages.assert_called_once_with()
        assert "artifact-123" in result
        assert "Test Chart" in result
        assert "A test visualization" in result

    async def test_arun_impl_artifacts_returns_no_artifacts_message(self):
        """Test that artifacts kind returns 'No artifacts available' when empty."""
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_conversation_artifact_messages = AsyncMock(return_value=[])
        context_manager.artifacts.check_user_has_billing_access = AsyncMock(return_value=False)

        tool = ReadDataTool(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, _ = await tool._arun_impl({"kind": "artifacts"})

        assert result == "No artifacts available"

    async def test_create_tool_class_with_artifacts(self):
        """Test that tool has artifacts in description when can_read_artifacts is True."""
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
            can_read_artifacts=True,
        )
        assert "# Artifacts" not in tool.description
        assert "billing_info" not in tool.description

    async def test_create_tool_class_with_artifacts_and_billing_access(self):
        """Test that tool has artifacts and billing in description when can_read_artifacts and can_read_billing are True."""
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
            can_read_artifacts=True,
        )
        assert "# Artifacts" not in tool.description
        assert "billing_info" in tool.description
        assert "Billing information" in tool.description

    async def test_read_insight_success(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        viz_content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test Insight",
            description="A test description",
        )
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_insight = AsyncMock(return_value=viz_content)

        with patch(
            "ee.hogai.tools.read_data.execute_and_format_query", AsyncMock(return_value="Formatted results here")
        ):
            tool = await ReadDataTool.create_tool_class(
                team=team,
                user=user,
                state=state,
                context_manager=context_manager,
            )

            result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123", "execute": True})

            assert "# Test Insight" in result
            assert "Description: A test description" in result
            assert "Query type: AssistantTrendsQuery" in result
            assert "Formatted results here" in result
            assert artifact is None

    async def test_read_insight_not_found(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_insight = AsyncMock(return_value=None)

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        with pytest.raises(MaxToolRetryableError) as exc_info:
            await tool._arun_impl({"kind": "insight", "insight_id": "nonexistent", "execute": False})

        assert "nonexistent" in str(exc_info.value)

    async def test_read_insight_without_execute(self):
        team = MagicMock()
        user = MagicMock()
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        context_manager = MagicMock()
        context_manager.check_user_has_billing_access = AsyncMock(return_value=False)

        viz_content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test Insight",
            description="A test description",
        )
        context_manager.artifacts = MagicMock()
        context_manager.artifacts.aget_insight = AsyncMock(return_value=viz_content)

        tool = await ReadDataTool.create_tool_class(
            team=team,
            user=user,
            state=state,
            context_manager=context_manager,
        )

        result, artifact = await tool._arun_impl({"kind": "insight", "insight_id": "abc123", "execute": False})

        assert "# Test Insight" in result
        assert "Description: A test description" in result
        assert "Query type: AssistantTrendsQuery" in result
        assert "Query definition:" in result
        assert artifact is None
