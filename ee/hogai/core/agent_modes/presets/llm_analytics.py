from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.search_traces import SearchLLMTracesTool
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_SEARCH_TRACES = """
User: Show me recent LLM traces
Assistant: I'll search for recent LLM traces from the past week.
*Uses search_llm_traces with dateRange: { date_from: "-7d" }*
""".strip()

POSITIVE_EXAMPLE_SEARCH_TRACES_REASONING = """
The assistant used the search tool because:
1. The user wants to see recent traces
2. The search_llm_traces tool can filter by date range
3. This is a straightforward search that doesn't require multiple steps
""".strip()

POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE = """
User: What's happening in my most expensive trace?
Assistant: I'll find the most expensive trace and then analyze it in detail.
*Creates todo list with the following items:*
1. Search for the most expensive trace
2. Read the trace details
3. Explain what happened
*Uses search_llm_traces with limit: 1 and ordered by cost*
After getting the trace, the assistant uses read_data with kind: "llm_trace" to get full details, then explains what happened.
""".strip()

POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE_REASONING = """
The assistant used the todo list because:
1. The user wants to understand the most expensive trace, not just see a list
2. This requires multiple steps: search to find it, read to get details, then explain
3. Breaking this into steps ensures the assistant gets all necessary data before explaining
""".strip()

LLM_ANALYTICS_MODE_DESCRIPTION = "Specialized mode for analyzing LLM traces. Search and read LLM traces to understand model usage, costs, latency, and errors."


class LLMAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SEARCH_TRACES,
            reasoning=POSITIVE_EXAMPLE_SEARCH_TRACES_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE,
            reasoning=POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [SearchLLMTracesTool]
        return tools


llm_analytics_agent = AgentModeDefinition(
    mode=AgentMode.LLM_ANALYTICS,
    mode_description=LLM_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=LLMAnalyticsAgentToolkit,
)


chat_agent_plan_llm_analytics_agent = AgentModeDefinition(
    mode=AgentMode.LLM_ANALYTICS,
    mode_description=LLM_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=LLMAnalyticsAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
