from uuid import uuid4

from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import AgentMode

from ee.hogai.tools.switch_mode import SwitchModeTool
from ee.hogai.utils.types import AssistantState


class TestSwitchModeTool(TestCase):
    def _build_tool(self, current_mode: AgentMode | None) -> SwitchModeTool:
        state = AssistantState(messages=[], root_tool_call_id=str(uuid4()), agent_mode=current_mode)
        tool = SwitchModeTool(team=MagicMock(), user=MagicMock(), state=state, context_manager=MagicMock())
        tool._mode_registry = {AgentMode.SQL: object(), AgentMode.PRODUCT_ANALYTICS: object()}  # type: ignore[assignment]
        return tool

    async def test_switching_to_current_mode_is_a_noop(self):
        tool = self._build_tool(AgentMode.SQL)

        content, new_mode = await tool._arun_impl(new_mode="sql")

        self.assertIn("already in", content)
        self.assertEqual(new_mode, AgentMode.SQL)

    async def test_switching_to_a_different_mode_succeeds(self):
        tool = self._build_tool(AgentMode.SQL)

        content, new_mode = await tool._arun_impl(new_mode="product_analytics")

        self.assertIn("Successfully switched", content)
        self.assertEqual(new_mode, "product_analytics")

    @parameterized.expand([("unknown",), ("not_a_mode",)])
    async def test_switching_to_unknown_mode_fails(self, bad_mode: str):
        tool = self._build_tool(AgentMode.SQL)

        content, new_mode = await tool._arun_impl(new_mode=bad_mode)

        self.assertIn("does not exist", content)
        self.assertEqual(new_mode, AgentMode.SQL)
