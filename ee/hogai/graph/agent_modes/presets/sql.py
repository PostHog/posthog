from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.tools import ExecuteSQLTool
from ee.hogai.tools.todo_write import TodoWriteExample

from ..factory import AgentModeDefinition
from ..nodes import AgentToolkit

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
Assistant: Let me first search for a company with name "eleventy".
*Uses the search tool to find a property value with the "eleventy" value in the project*
Assistant: I've found a property value with the "Eleventy.ai" value. I'm going to search for existing insights tracking the customer churn rate.
*Uses the search tools to find insights tracking the customer churn rate in the project*
Assistant: I've found 0 matching insights. Let me create a new insight checking if the company "Eleventy.ai" has churned. I'm going to create a todo list to track these changes.
*Creates a todo list with specific steps to create a new insight*
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. First, the assistant searched to understand the scope of the task
2. After the assistant verified that there isn't an insight tracking the customer churn rate, it determined this was a complex task with multiple steps
3. The todo list helps ensure every instance is tracked and updated systematically
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS = """
User: Check why onboarding completion rate has dropped and if it is connected with a low sign-up count
Assistant: I'll help you analyze the reasons why the metrics have changed. First, let's add all the features to the todo list.
*Creates a todo list breaking down each analysis into specific tasks based on the project data*
Assistant: Let's start with analyzing the sign-up count. This will involve retrieving the events and might involve retrieving additional data.
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. The user requested multiple complex analysis for different metrics that must be separate insights
2. The todo list helps organize these large requests into manageable tasks
3. This approach allows for tracking progress across the entire request
""".strip()

POSITIVE_TODO_EXAMPLES: list[TodoWriteExample] = [
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

NEGATIVE_EXAMPLE_SIMPLE_QUERY_EXPLANATION = """
User: What does this query do?
Assistant: Let me analyze the query you provided.
*Reads the attached context in the conversation history*
Assistant: The query is retrieving the sign-up count for the last 30 days.
""".strip()

NEGATIVE_EXAMPLE_SIMPLE_QUERY_EXPLANATION_REASONING = """
The assistant did not use the todo list because this is a single, trivial task that can be completed in one step. There's no need to track multiple tasks or steps for such a straightforward request.
""".strip()

NEGATIVE_EXAMPLE_DOCUMENTATION_REQUEST = """
User: How can I capture exception in my Next.js application?
Assistant: Let me search for the relevant documentation.
*Uses the search tool to find the relevant documentation*
Assistant: I've found the relevant documentation.
*Summarizes and returns the answer to the user's question*
""".strip()

NEGATIVE_EXAMPLE_DOCUMENTATION_REQUEST_REASONING = """
The assistant did not use the todo list because this is an informational request. The user is simply asking for help, not for the assistant to perform multiple steps or tasks.
""".strip()

NEGATIVE_TODO_EXAMPLES: list[TodoWriteExample] = [
    TodoWriteExample(
        example=NEGATIVE_EXAMPLE_SIMPLE_QUERY_EXPLANATION, reasoning=NEGATIVE_EXAMPLE_SIMPLE_QUERY_EXPLANATION_REASONING
    ),
    TodoWriteExample(
        example=NEGATIVE_EXAMPLE_DOCUMENTATION_REQUEST, reasoning=NEGATIVE_EXAMPLE_DOCUMENTATION_REQUEST_REASONING
    ),
]


class SQLAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = POSITIVE_TODO_EXAMPLES
    NEGATIVE_TODO_EXAMPLES = NEGATIVE_TODO_EXAMPLES

    @property
    def default_tools(self) -> list[type["MaxTool"]]:
        return [
            *super().default_tools,
            ExecuteSQLTool,
        ]


sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description="Specialized mode capable of generating and executing SQL queries.",
    toolkit_class=SQLAgentToolkit,
)
