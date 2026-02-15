from dataclasses import replace
from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import (
    ChatAgentExecutable,
    ChatAgentPlanExecutable,
    ChatAgentPlanToolsExecutable,
    ChatAgentToolsExecutable,
)
from ee.hogai.tools import CreateInsightTool, UpsertDashboardTool
from ee.hogai.tools.todo_write import POSITIVE_TODO_EXAMPLES, TodoWriteExample

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE = """
User: Generate a revenue dashboard
Assistant: I'll help you create a revenue dashboard. Let me make a todo list to track this implementation.
1. List (the list_data tool with kind="dashboards") the existing dashboards
2. List saved insights using the list_data tool with kind="insights"
3. Validate promising insights by reading their schemas (the read_data tool with insight_id)
4. Retrieve the taxonomy and understand the schema (the read_taxonomy tool)
5. Retrieve the data warehouse schema to find the relevant tables (the read_data tool)
6. Create new insights for missing metrics only if no existing insight matches
7. Create a new dashboard with the insights
8. Analyze the created dashboard and provide a concise summary of metrics
*Begins working on the first task*
""".strip()

DASHBOARD_CREATION_TODO_EXAMPLE_REASONING = """
The assistant used the todo list because:
1. The user requested to create a dashboard. This is a complex task that requires multiple steps to complete.
2. Finding existing insights requires both listing (to discover insights with different naming using the list_data tool) and searching (by keywords using the search tool).
3. Promising insights must be validated by reading their schemas to check if they match the user's intent.
4. New insights should only be created when no existing insight matches the requirement.
""".strip()

MODE_DESCRIPTION = "General-purpose mode for product analytics tasks."


class ProductAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        *POSITIVE_TODO_EXAMPLES,
        TodoWriteExample(
            example=DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE,
            reasoning=DASHBOARD_CREATION_TODO_EXAMPLE_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [CreateInsightTool, UpsertDashboardTool]


product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=ProductAnalyticsAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)


class ReadOnlyProductAnalyticsAgentToolkit(AgentToolkit):
    """Product analytics toolkit for readonly operations — excludes UpsertDashboardTool (dangerous operation)."""

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [CreateInsightTool]


subagent_product_analytics_agent = replace(product_analytics_agent, toolkit_class=ReadOnlyProductAnalyticsAgentToolkit)

chat_agent_plan_product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=ReadOnlyProductAnalyticsAgentToolkit,  # Only CreateInsightTool
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
