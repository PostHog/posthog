import asyncio
from typing import TypedDict, cast

import pytest

from braintrust import EvalCase, Score
from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery, HumanMessage, VisualizationMessage

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database

from posthog.models import Team
from posthog.sync import database_sync_to_async

from ee.hogai.eval.base import MaxPrivateEval
from ee.hogai.eval.offline.conftest import EvaluationContext
from ee.hogai.eval.schema import DatasetInput
from ee.hogai.eval.scorers.sql import SQLSemanticsCorrectness, SQLSyntaxCorrectness
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.warehouse import serialize_database_schema
from ee.models import Conversation


class EvalOutput(BaseModel):
    database_schema: str
    query_kind: str | None = Field(default=None)
    sql_query: str | None = Field(default=None)


class EvalMetadata(TypedDict):
    team_id: int


async def serialize_database(team: Team):
    database = await database_sync_to_async(create_hogql_database)(team=team)
    context = HogQLContext(team=team, database=database, enable_select_queries=True)
    return await serialize_database_schema(database, context)


@pytest.fixture
def call_graph(eval_ctx: EvaluationContext):
    async def callable(entry: DatasetInput, *args, **kwargs) -> EvalOutput:
        team = await Team.objects.aget(id=entry.team_id)
        conversation, database_schema = await asyncio.gather(
            Conversation.objects.acreate(team=team, user=eval_ctx.user),
            serialize_database(team),
        )
        graph = AssistantGraph(team, eval_ctx.user).compile_full_graph()

        state = await graph.ainvoke(
            AssistantState(messages=[HumanMessage(content=entry.input["query"])]),
            {
                "configurable": {
                    "thread_id": conversation.id,
                    "user": eval_ctx.user,
                    "team": team,
                    "distinct_id": eval_ctx.user.distinct_id,
                }
            },
        )
        maybe_viz_message = find_last_message_of_type(state["messages"], VisualizationMessage)
        if maybe_viz_message:
            return EvalOutput(
                database_schema=database_schema,
                query_kind=maybe_viz_message.answer.kind,
                sql_query=maybe_viz_message.answer.query
                if isinstance(maybe_viz_message.answer, AssistantHogQLQuery)
                else None,
            )
        return EvalOutput(database_schema=database_schema)

    return callable


async def sql_semantics_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    metric = SQLSemanticsCorrectness()
    return await metric.eval_async(
        input=input.input["query"], expected=expected, output=output.sql_query, database_schema=output.database_schema
    )


async def sql_syntax_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    metric = SQLSyntaxCorrectness()
    return await metric.eval_async(
        input=input.input["query"], expected=expected, output=output.sql_query, database_schema=output.database_schema
    )


def generate_test_cases(eval_ctx: EvaluationContext):
    for entry in eval_ctx.dataset:
        metadata: EvalMetadata = {"team_id": entry.team_id}
        yield EvalCase(input=entry, expected=entry.expected["output"], metadata=cast(dict, metadata))


@pytest.mark.django_db
async def eval_offline_sql(eval_ctx: EvaluationContext, call_graph, pytestconfig):
    await MaxPrivateEval(
        experiment_name=eval_ctx.experiment_name,
        task=call_graph,
        scores=[sql_syntax_scorer, sql_semantics_scorer],
        data=generate_test_cases(eval_ctx),
        pytestconfig=pytestconfig,
    )
