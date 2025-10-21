from typing import Annotated, Literal

from django.conf import settings

from langchain_core.runnables import RunnableLambda
from langchain_core.tools import InjectedToolCallId
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from ee.hogai.graph.insights.nodes import InsightSearchNode, NoInsightsException
from ee.hogai.tool import MaxSubtool, MaxTool, ToolMessagesArtifact
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState

SEARCH_TOOL_PROMPT = """
Use this tool to search docs or insights by using natural language.

# Documentation search

This tool is absolutely NECESSARY to answer PostHog-related questions accurately, as our product and docs change all the time:
- How to use PostHog
- How to use PostHog features
- How to contact support or other humans
- How to report bugs
- How to submit feature requests
- To troubleshoot something
- What default fields and properties are available for events and persons
- …Or anything else PostHog-related

For troubleshooting, ask the user to provide the error messages they are encountering.
If no error message is involved, ask the user to describe their expected results vs. the actual results they're seeing.
You avoid suggesting things that the user has told you they've already tried.

Examples:
- Needs help understanding PostHog concepts
- Has questions about SDK integration or instrumentation
    - e.g. `posthog.capture('event')`, `posthog.captureException(err)`,
    `posthog.identify(userId)`, `capture({ ... })` not working, etc.
- Troubleshooting missing or unexpected data
    - e.g. "Events aren't arriving", "Why don't I see errors on the dashboard?"
- Wants to know more about PostHog the company
- Has questions about incidents or system status
- Has disabled session replay and needs help turning it back on
- Reports an issue with PostHog
- Wants to delete events from PostHog

If the user's question should be satisfied by using insights, do that before answering using documentation.

# Insights search

Use this tool when you can assume that an insight you want to analyze was already created by the user.

Examples:
- Product-specific metrics that most likely exist.
- Common sense metrics that are relevant to the product.
""".strip()


SearchKind = Literal["insights"] | Literal["docs"]


class SearchToolArgs(BaseModel):
    tool_call_id: Annotated[str, InjectedToolCallId, SkipJsonSchema]
    kind: SearchKind = Field(description="Select the entity you want to find")
    query: str = Field(
        description="Describe what you want to find. Include as much details from the context as possible."
    )


class SearchTool(MaxTool):
    name: Literal["search"] = "search"
    description: str = SEARCH_TOOL_PROMPT
    thinking_message: str = "Searching for information"
    context_prompt_template: str = "Searches documentation or user data in PostHog (insights)"
    args_schema: type[BaseModel] = SearchToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(
        self, kind: SearchKind, query: str, tool_call_id: str
    ) -> tuple[str, ToolMessagesArtifact | None]:
        match kind:
            case "docs":
                if not settings.INKEEP_API_KEY:
                    return "This tool is not available in this environment.", None
                docs_tool = InkeepDocsSearchTool(self._team, self._user, self._state, self._context_manager)
                return await docs_tool.execute(query, tool_call_id)
            case "insights":
                insights_tool = InsightSearchTool(self._team, self._user, self._state, self._context_manager)
                return await insights_tool.execute(query, tool_call_id)
            case _:
                raise ValueError(f"Unknown kind argument of the {self.get_name()} tool")


class InkeepDocsSearchTool(MaxSubtool):
    async def execute(self, query: str, tool_call_id: str) -> tuple[str, ToolMessagesArtifact | None]:
        # Avoid circular import
        from ee.hogai.graph.inkeep_docs.nodes import InkeepDocsNode

        # Init the graph
        node = InkeepDocsNode(self._team, self._user)
        chain: RunnableLambda[AssistantState, PartialAssistantState | None] = RunnableLambda(node)
        copied_state = self._state.model_copy(deep=True, update={"root_tool_call_id": tool_call_id})
        result = await chain.ainvoke(copied_state)
        assert result is not None
        return "", ToolMessagesArtifact(messages=result.messages)


EMPTY_DATABASE_ERROR_MESSAGE = """
The user doesn't have any insights created yet.
""".strip()


class InsightSearchTool(MaxSubtool):
    async def execute(self, query: str, tool_call_id: str) -> tuple[str, ToolMessagesArtifact | None]:
        try:
            node = InsightSearchNode(self._team, self._user)
            copied_state = self._state.model_copy(
                deep=True, update={"search_insights_query": query, "root_tool_call_id": tool_call_id}
            )
            chain: RunnableLambda[AssistantState, PartialAssistantState | None] = RunnableLambda(node)
            result = await chain.ainvoke(copied_state)
            return "", ToolMessagesArtifact(messages=result.messages) if result else None
        except NoInsightsException:
            return EMPTY_DATABASE_ERROR_MESSAGE, None
