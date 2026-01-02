from typing import TYPE_CHECKING

from posthog.schema import AgentMode

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


class ErrorTrackingAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SEARCH_ERRORS,
            reasoning=POSITIVE_EXAMPLE_SEARCH_ERRORS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.error_tracking.backend.tools.search_issues import SearchErrorTrackingIssuesTool

        tools: list[type[MaxTool]] = [SearchErrorTrackingIssuesTool]
        return tools


error_tracking_agent = AgentModeDefinition(
    mode=AgentMode.ERROR_TRACKING,
    mode_description="Specialized mode for analyzing error tracking issues. This mode allows you to search and filter error tracking issues by status, date range, frequency, and other criteria.",
    toolkit_class=ErrorTrackingAgentToolkit,
)
