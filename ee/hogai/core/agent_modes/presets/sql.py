from typing import TYPE_CHECKING

from posthog.schema import AgentMode

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
1. Find the relevant data warehouse tables having financial data to create an SQL query
2. Find in the tables a column that can be used to associate a user with the PostHog's default table "persons."
3. Retrieve person properties to narrow down data to users from specific country
4. Execute the SQL query
5. Analyze retrieved data
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
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS = """
User: Has eleventy churned?
Assistant: Let me first check the insights or events and properties to understand how we can track churn.
*Uses the search tool to find insights and the read_taxonomy tool to find events and properties that can be used to track churn*
Assistant: I haven't found any combinations of events and properties that can be used to track churn. Let me check how we can identify the company by a name in the project.
*Uses the read_taxonomy tool to find properties that can be used to identify the company by a name in the project*
Assistant: I've found properties that can be used to identify the company by a name in the project. I'm going to create an SQL query to find a specific company by a name.
*Creates a todo list with specific steps to create a new SQL query*
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. First, the assistant searched to understand the scope of the task
2. After the assistant verified that there isn't an insight or combination of events and properties tracking the customer churn rate, it determined this was a complex task with multiple steps
3. The todo list helps ensure every instance is tracked and updated systematically
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
    mode_description="Specialized mode capable of generating and executing SQL queries. This mode allows you to query the ClickHouse database, which contains both data collected by PostHog (events, groups, persons, sessions) and data warehouse sources connected by the user, such as SQL tables, CRMs, and external systems. This mode can also be used to search for specific data that can be used in other modes.",
    toolkit_class=SQLAgentToolkit,
)
