from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase
from pydantic import BaseModel

from ee.hogai.eval.conftest import MaxEval
from ee.hogai.eval.eval_sql import SQLSyntaxCorrectness
from ee.hogai.eval.scorers import PlanAndQueryOutput
from ee.hogai.utils.types import AssistantState
from products.data_warehouse.backend.max_tools import HogQLGeneratorArgs, HogQLGeneratorTool


class EvalInput(BaseModel):
    instructions: str
    current_query: str | None = None
    apply_patch: Callable[[HogQLGeneratorTool], Any] | None = None


@pytest.fixture
def call_generate_hogql_query(demo_org_team_user):
    _, team, user = demo_org_team_user

    async def callable(inputs: EvalInput) -> PlanAndQueryOutput:
        # Initial state for the graph
        tool = HogQLGeneratorTool(AssistantState(messages=[]))

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

        return result.artifact

    return callable


@pytest.mark.django_db
async def eval_tool_generate_hogql_query(call_generate_hogql_query):
    await MaxEval(
        experiment_name="tool_generate_hogql_query",
        task=call_generate_hogql_query,
        scores=[SQLSyntaxCorrectness(), AnswerSimilarity()],
        data=[
            EvalCase(
                input=EvalInput(instructions="List all events from the last 7 days"),
                expected="SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 day",
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
            ),
            EvalCase(
                input=EvalInput(
                    instructions="how many bills did users pay from Australia? Output just a single number.",
                    apply_patch=lambda tool: patch.object(
                        tool,
                        "_aget_core_memory_text",
                        return_value='Use "paid_bill" event from the events table joined by "event.person_id = person.id". The person properties have the "$country" field with two-letter country codes (uppercase).',
                    ),
                ),
                expected="SELECT count() FROM events INNER JOIN persons ON event.person_id = person.id WHERE event = 'paid_bill' AND person.properties.$country = 'AU'",
            ),
        ],
    )
