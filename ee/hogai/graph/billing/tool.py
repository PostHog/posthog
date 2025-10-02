from typing import cast

import structlog

from posthog.schema import AssistantTool, AssistantToolCallMessage

from ee.hogai.graph.billing.nodes import BillingNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, ToolResult

logger = structlog.get_logger(__name__)


class RetrieveBillingInformationTool(MaxTool):
    name = AssistantTool.GET_BILLING_INFO.value
    description = """
    Retrieve detailed billing information for the current organization.
    Use this tool when the user asks about billing, subscription, usage, or spending related questions.
    """

    async def _arun_impl(self) -> ToolResult:
        state = self._state
        if not state:
            raise ValueError("State is required")
        state = cast(AssistantState, state)
        node = BillingNode(team=self._team, user=self._user)
        result = await node.arun(state, self._config)
        if not result or not result.messages:
            logger.warning("Task failed: no messages received from node executor", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        last_message = result.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning("Task failed: last message is not AssistantToolCallMessage", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        return await self._successful_execution(last_message.content, [])
