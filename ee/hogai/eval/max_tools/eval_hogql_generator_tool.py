from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from braintrust import EvalCase, Score
from pydantic import BaseModel

from ee.hogai.eval.conftest import MaxEval
from ee.hogai.eval.eval_sql import SQLSyntaxCorrectness
from ee.hogai.eval.scorers import SQLSemanticsCorrectness
from ee.hogai.utils.markdown import remove_markdown
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.warehouse import serialize_database_schema
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.sync import database_sync_to_async
from products.data_warehouse.backend.max_tools import HogQLGeneratorArgs, HogQLGeneratorTool


class EvalInput(BaseModel):
    instructions: str
    current_query: str | None = None
    apply_patch: Callable[[HogQLGeneratorTool], Any] | None = None


@pytest.fixture
def call_generate_hogql_query(demo_org_team_user):
    _, team, user = demo_org_team_user

    async def callable(inputs: EvalInput, *args, **kwargs) -> str:
        # Initial state for the graph
        tool = HogQLGeneratorTool(team=team, user=user, state=AssistantState(messages=[]))

        if inputs.apply_patch:
            inputs.apply_patch(tool)

        # Invoke the graph. The state will be updated through planner and then generator.
        result = await tool.ainvoke(
            HogQLGeneratorArgs(instructions=inputs.instructions).model_dump(),
            {
                "configurable": {
                    "team": team,
                    "user": user,
                    "contextual_tools": {
                        tool.name: {
                            "current_query": inputs.current_query,
                        },
                    },
                }
            },
        )

        return remove_markdown(result)

    return callable


@pytest.fixture
async def database_schema(demo_org_team_user):
    team = demo_org_team_user[1]
    database = await database_sync_to_async(create_hogql_database)(team=team)
    context = HogQLContext(team=team, enable_select_queries=True, database=database)
    return await serialize_database_schema(database, context)


async def sql_semantics_scorer(input: EvalInput, expected: str, output: str, metadata: dict) -> Score:
    metric = SQLSemanticsCorrectness()
    return await metric.eval_async(
        input=input.instructions, expected=expected, output=output, database_schema=metadata["schema"]
    )


@pytest.mark.django_db
async def eval_tool_generate_hogql_query(call_generate_hogql_query, database_schema):
    metadata = {"schema": database_schema}

    await MaxEval(
        experiment_name="tool_generate_hogql_query",
        task=call_generate_hogql_query,
        scores=[SQLSyntaxCorrectness(), sql_semantics_scorer],
        data=[
            EvalCase(
                input=EvalInput(instructions="List all events from the last 7 days"),
                expected="SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 day",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        # This erroneously says "logs are stored in a table named 'console_logs'". Whether it was
                        # the root node that pulled it out of its ass, or the user - we should handle this gracefully
                        "Write an SQL query to find console logs where the level is error. "
                        "Assume the logs are stored in a table named 'console_logs'."
                    ),
                ),
                expected="SELECT * FROM log_entries WHERE level = 'error'",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        # This is a test case for the bug where the tool would generate a JOIN query with relational operators in the JOIN condition.
                        # We want to make sure that the tool refuses to generate such a query and instead generates a CROSS JOIN with WHERE clause.
                        "Write an SQL query to find events with their person names using a JOIN clause. "
                        "You MUST USE relational operators. Create a JOIN query with timestamp > created_at in the JOIN condition. "
                        "JOIN events with persons where event timestamp is greater than person created_at. Use JOIN with e.timestamp > p.created_at in the ON clause."
                    )
                ),
                expected="SELECT e.uuid, e.event, e.timestamp, p.properties.name AS person_name FROM events e CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        "Write an SQL query to join events with persons where event timestamp is greater than person created_at. Use JOIN with relational operators."
                    )
                ),
                expected="SELECT e.event, p.properties.name FROM events AS e CROSS JOIN persons AS p WHERE e.person_id = p.id AND e.timestamp > p.created_at",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="how many bills did users pay from Australia? Output just a single number.",
                    apply_patch=lambda tool: patch.object(
                        tool,
                        "_aget_core_memory_text",
                        return_value='Use "paid_bill" event from the events table joined by "events.person_id = persons.id". The person properties have the "$country" field with two-letter country codes (uppercase).',
                    ).start(),
                ),
                expected="SELECT count() FROM events INNER JOIN persons ON events.person_id = persons.id WHERE events.event = 'paid_bill' AND persons.properties.$country = 'AU'",
                metadata=metadata,
            ),
        ],
    )
