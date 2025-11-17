from uuid import uuid4

from unittest.mock import AsyncMock, MagicMock, patch

from ee.hogai.tools.read_data import (
    READ_DATA_BILLING_PROMPT,
    READ_DATA_PROMPT,
    ReadDataAdminAccessToolArgs,
    ReadDataTool,
    ReadDataToolArgs,
)
from ee.hogai.utils.types import AssistantState


class TestReadDataTool:
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

        # Should use the admin access args schema
        assert tool.args_schema == ReadDataAdminAccessToolArgs

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

        # Should use the basic args schema
        assert tool.args_schema == ReadDataToolArgs

        # Description should NOT include billing prompt
        assert "billing_info" not in tool.description
        assert "Billing information" not in tool.description

        # Should still have base prompt content
        assert "data warehouse" in tool.description

    async def test_create_tool_class_formats_prompt_correctly(self):
        """Test that format_prompt_string correctly injects billing_prompt."""
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

        # The formatted description should contain both base prompt and billing prompt
        expected_description = READ_DATA_PROMPT.replace(
            "{{{billing_prompt}}}", READ_DATA_BILLING_PROMPT.strip()
        ).strip()
        assert tool.description == expected_description

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
