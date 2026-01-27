from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_SEARCH_ERRORS = """
User: Show me the most frequent errors from the last week
Assistant: I'll search for the most frequent error tracking issues from the past week.
*Uses search_error_tracking_issues with orderBy: "occurrences" and dateRange: { date_from: "-7d" }*
""".strip()

POSITIVE_EXAMPLE_SEARCH_ERRORS_REASONING = """
The assistant used the search tool because:
1. The user wants to find errors based on frequency criteria
2. The search_error_tracking_issues tool can filter by date range and order by occurrences
3. This is a straightforward search that doesn't require multiple steps
""".strip()

POSITIVE_EXAMPLE_SEARCH_AND_EXPLAIN = """
User: What's causing our most frequent error?
Assistant: I'll search for the most frequent error and then explain what's causing it.
*Creates todo list with the following items:*
1. Search for the most frequent error tracking issue
2. Read the issue's stack trace data
3. Analyze and explain the root cause
*Uses search_error_tracking_issues with orderBy: "occurrences" and limit: 1*
After getting the issue, the assistant uses read_data with kind: "error_tracking_issue" and the issue_id to get the stack trace, then analyzes and explains it.
""".strip()

POSITIVE_EXAMPLE_SEARCH_AND_EXPLAIN_REASONING = """
The assistant used the todo list because:
1. The user wants to understand the root cause, not just see a list
2. This requires multiple steps: first find the issue, then read its stack trace, then analyze it
3. The read_data tool with error_tracking_issue kind retrieves the stack trace for analysis
4. Breaking this into steps ensures the assistant gets all necessary data before explaining
""".strip()

POSITIVE_EXAMPLE_IMPACT_ANALYSIS = """
User: What's the impact of errors on our checkout flow?
Assistant: I'll help you analyze how error tracking issues are impacting your checkout flow.
*Uses read_taxonomy to find checkout-related events*
Based on your event taxonomy, the checkout-related events are: checkout_started, payment_submitted, and order_completed. These are the events you should analyze to understand which issues may be blocking or affecting your checkout conversion.
""".strip()

MODE_DESCRIPTION = "Specialized mode for analyzing error tracking issues. This mode allows you to search and filter error tracking issues by status, date range, frequency, and other criteria. You can also retrieve detailed stack trace information for any issue to analyze and explain its root cause."

POSITIVE_EXAMPLE_IMPACT_ANALYSIS_REASONING = """
The assistant used the read_taxonomy tool because:
1. The user wants to understand how issues affect a specific product flow (checkout)
2. read_taxonomy is used to find relevant event names for the checkout flow
3. The assistant identifies which events relate to the user's query:
   - "issues blocking signup" → signup-related events (sign_up_started, signup_complete)
   - "notebook errors" → notebook events (notebook_created, notebook_updated)
   - "checkout problems" → checkout events (checkout_started, payment_submitted, order_completed)
4. The assistant explains which events are relevant for impact analysis
""".strip()


class ErrorTrackingAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SEARCH_ERRORS,
            reasoning=POSITIVE_EXAMPLE_SEARCH_ERRORS_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SEARCH_AND_EXPLAIN,
            reasoning=POSITIVE_EXAMPLE_SEARCH_AND_EXPLAIN_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_IMPACT_ANALYSIS,
            reasoning=POSITIVE_EXAMPLE_IMPACT_ANALYSIS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.error_tracking.backend.tools.search_issues import SearchErrorTrackingIssuesTool

        tools: list[type[MaxTool]] = [SearchErrorTrackingIssuesTool]
        return tools


error_tracking_agent = AgentModeDefinition(
    mode=AgentMode.ERROR_TRACKING,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=ErrorTrackingAgentToolkit,
)


chat_agent_plan_error_tracking_agent = AgentModeDefinition(
    mode=AgentMode.ERROR_TRACKING,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=ErrorTrackingAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
