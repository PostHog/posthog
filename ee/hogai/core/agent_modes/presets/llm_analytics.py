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

POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL = """
User: Write a Hog eval that checks if the output is longer than 10 characters
Assistant: I'll write a Hog evaluation and test it against your recent events.
*Uses run_hog_eval_test with source: 'let result := length(output) > 10; print(concat("Output length: ", toString(length(output)))); return result;'*
""".strip()

POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL_REASONING = """
The assistant used run_hog_eval_test because:
1. The user wants to create a Hog evaluation that checks output length
2. The tool compiles and runs the code against real events to verify it works
3. The results show whether the evaluation logic is correct
""".strip()

POSITIVE_EXAMPLE_FIX_EVAL_ERRORS = """
User: The eval is failing with a null error on some events
Assistant: I'll fix the null handling and test again.
*Uses run_hog_eval_test with updated source that adds null checks*
After seeing the results, the assistant explains what was fixed.
""".strip()

POSITIVE_EXAMPLE_FIX_EVAL_ERRORS_REASONING = """
The assistant used run_hog_eval_test because:
1. The user reported errors in the evaluation code
2. Testing with the tool reveals which events cause null errors
3. The assistant can iterate on the fix by running the tool again
""".strip()

LLM_ANALYTICS_MODE_DESCRIPTION = "Specialized mode for LLM analytics. Search and analyze LLM traces for usage, costs, latency, and errors. Write and test Hog evaluation code against real events."


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
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL,
            reasoning=POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_FIX_EVAL_ERRORS,
            reasoning=POSITIVE_EXAMPLE_FIX_EVAL_ERRORS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.llm_analytics.backend.tools.run_hog_eval_test import RunHogEvalTestTool

        return [SearchLLMTracesTool, RunHogEvalTestTool]


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
