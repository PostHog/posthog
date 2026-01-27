from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.tools import ExecuteSQLTool
from ee.hogai.tools.todo_write import TodoWriteExample

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION = """
User: what is our ARR from the US?
Assistant: I'll help you find your current ARR from the US users. Let me create a todo list to track this implementation.
*Creates todo list with the following items:*
1. Read the core data warehouse schema to see what tables are available (events, persons, groups, sessions, and list of warehouse tables)
2. Read specific warehouse table schemas that might contain financial/revenue data
3. Find a column in the financial tables that can be used to join with the persons table
4. Write SQL query joining financial data with persons to filter by country property
5. Execute the SQL query and analyze retrieved data
6. Analyze the retrieved data
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION_REASONING = """
The assistant used the todo list because:
1. Creating an SQL query (insight) requires understanding the taxonomy and data warehouse tables: events, properties, property values, and data warehouse tables relevant to the user's query.
2. The data warehouse schema is complex and requires understanding the relationships between tables and columns.
3. The user query requests additional segmentation using their data schema.
4. Property values might require retrieving sample property values to understand the data better.
5. Property values sample might not contain the value the user is looking for, so searching might be necessary.
6. Taxonomy and data warehouse schema might have multiple combinations of data that will equally answer the question.
7. Multiple warehouse tables might contain financial data, so progressive reading helps identify the right one.
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS = """
User: Has eleventy churned?
Assistant: Let me first check the insights or events and properties to understand how we can track churn.
*Uses the search tool to find insights and the read_taxonomy tool to find events and properties that can be used to track churn*
Assistant: I haven't found existing churn insights. Let me read the data warehouse schema to see what tables are available.
*Uses read_data with data_warehouse_schema to see core tables and available warehouse tables*
Assistant: I see there's a subscriptions table. Let me get its full schema.
*Uses read_data with data_warehouse_table to get the subscriptions table schema*
Assistant: Now I can write an SQL query to check if eleventy has churned based on their subscription status.
*Creates a todo list with the remaining steps to execute and analyze the query*
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. First, the assistant searched existing insights and taxonomy to understand what's already available
2. Then progressively read the data warehouse: first the overview to see available tables, then specific table schemas
3. This progressive approach avoided loading unnecessary schema information while identifying the right data source
4. The todo list helps ensure every instance is tracked and updated systematically
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS = """
User: Check why onboarding completion rate has dropped and if it is connected with a low sign-up count
Assistant: I'll help you analyze the reasons why the metrics have changed. First, let's add all the features to the todo list.
*Creates a todo list breaking down each analysis into specific tasks based on the project data*
Assistant: Let's start with writing the SQL query for the sign-up count. This will involve retrieving the events and might involve retrieving additional data.
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. The user requested multiple complex analysis for different metrics that must be separate SQL queries
2. The todo list helps organize these large requests into manageable tasks
3. This approach allows for tracking progress across the entire request
""".strip()

MODE_DESCRIPTION = "Specialized mode capable of generating and executing SQL queries. This mode allows you to query the ClickHouse database, which contains both data collected by PostHog (events, groups, persons, sessions) and data warehouse sources connected by the user, such as SQL tables, CRMs, and external systems. This mode can also be used to search for specific data that can be used in other modes."


class SQLAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION,
            reasoning=POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS, reasoning=POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS,
            reasoning=POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [
            ExecuteSQLTool,
        ]


sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=SQLAgentToolkit,
)


chat_agent_plan_sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=SQLAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
