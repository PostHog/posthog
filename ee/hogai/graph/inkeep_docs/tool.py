from typing import cast

import structlog

from posthog.schema import AssistantTool, AssistantToolCallMessage

from ee.hogai.graph.inkeep_docs.nodes import InkeepDocsNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, ToolResult

logger = structlog.get_logger(__name__)


class SearchDocumentationTool(MaxTool):
    name = AssistantTool.SEARCH_DOCS.value
    description = """
    Answer the question using the latest PostHog documentation. This performs a documentation search.
    PostHog docs and tutorials change frequently, which makes this tool required.
    Do NOT use this tool if the necessary information is already in the conversation or context (except when you need to check whether an assumption presented is correct or not).
    """

    async def _arun_impl(self, search_documentation_query: str) -> ToolResult:
        state = self._state
        if not state:
            raise ValueError("State is required")
        state = cast(AssistantState, state)
        node = InkeepDocsNode(team=self._team, user=self._user)
        result = await node.arun(state, self._config)
        if not result or not result.messages:
            logger.warning("Task failed: no messages received from node executor", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        last_message = result.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning("Task failed: last message is not AssistantToolCallMessage", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        return await self._successful_execution(last_message.content)
