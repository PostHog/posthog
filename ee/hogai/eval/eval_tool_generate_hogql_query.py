import pytest
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase

from ee.hogai.eval.eval_sql import SQLSyntaxCorrectness
from products.data_warehouse.backend.max_tools import HogQLGeneratorTool

from .conftest import MaxEval


@pytest.fixture
def call_generate_hogql_query(demo_org_team_user):
    def callable(instructions: str) -> str:
        """Call the HogQLGeneratorTool and return the generated SQL query."""
        tool = HogQLGeneratorTool()
        tool._team = demo_org_team_user[1]
        tool._user = demo_org_team_user[2]
        tool._context = {"current_query": ""}

        # The tool returns a tuple of (formatted_sql, raw_sql)
        _, raw_sql = tool._run_impl(instructions)
        return raw_sql

    return callable


@pytest.mark.django_db
async def eval_tool_generate_hogql_query(call_generate_hogql_query):
    await MaxEval(
        experiment_name="tool_generate_hogql_query",
        task=call_generate_hogql_query,
        scores=[SQLSyntaxCorrectness(), AnswerSimilarity()],
        data=[
            EvalCase(
                input="List all events from the last 7 days",
                expected="SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 day",
            ),
            EvalCase(
                input=(
                    # This erroneously says "logs are stored in a table named 'console_logs'". Whether it was
                    # the root node that pulled it out of its ass, or the user - we should handle this gracefully
                    "Write an SQL query to find console logs where the level is error. "
                    "Assume the logs are stored in a table named 'console_logs'."
                ),
                expected="SELECT * FROM log_entries WHERE level = 'error'",
            ),
        ],
    )
