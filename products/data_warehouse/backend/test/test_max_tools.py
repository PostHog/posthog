from unittest.mock import patch

from ee.hogai.utils.types import AssistantState
from posthog.schema import AssistantToolCall
from posthog.test.base import NonAtomicBaseTest
from products.data_warehouse.backend.max_tools import HogQLGeneratorTool


class TestDataWarehouseMaxTools(NonAtomicBaseTest):
    async def test_hogql_generator_tool(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        with patch(
            "products.data_warehouse.backend.max_tools.HogQLGeneratorTool._model",
            return_value={"query": "SELECT AVG(properties.$session_length) FROM events"},
        ):
            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What is the average session length?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config)
            self.assertEqual(result.content, "```sql\nSELECT AVG(properties.$session_length) FROM events\n```")
