import asyncio
from typing import TypedDict, cast

import pytest

from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery, HumanMessage

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models import Team
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.utils import unwrap_visualization_artifact_content
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.eval.base import MaxPrivateEval
from ee.hogai.eval.offline.conftest import EvaluationContext, capture_score, get_eval_context
from ee.hogai.eval.schema import DatasetInput
from ee.hogai.eval.scorers.sql import SQLSemanticsCorrectness, SQLSyntaxCorrectness
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.hogai.utils.warehouse import serialize_database_schema
from ee.models import Conversation


class EvalOutput(BaseModel):
    database_schema: str
    query_kind: str | None = Field(default=None)
    sql_query: str | None = Field(default=None)


class EvalMetadata(TypedDict):
    team_id: int


async def serialize_database(team: Team):
    database = await database_sync_to_async(Database.create_for)(team=team)
    context = HogQLContext(team=team, database=database, enable_select_queries=True)
    return await serialize_database_schema(database, context)


async def call_graph(entry: DatasetInput, *args):
    eval_ctx = get_eval_context()
    team = await Team.objects.aget(id=entry.team_id)
    conversation, database_schema = await asyncio.gather(
        Conversation.objects.acreate(team=team, user=eval_ctx.user),
        serialize_database(team),
    )
    graph = AssistantGraph(team, eval_ctx.user).compile_full_graph()

    config = RunnableConfig(
        callbacks=cast(list, eval_ctx.get_callback_handlers(entry.trace_id)),
        configurable={
            "thread_id": conversation.id,
            "team": team,
            "user": eval_ctx.user,
            "distinct_id": eval_ctx.distinct_id,
        },
    )
    state = await graph.ainvoke(
        AssistantState(messages=[HumanMessage(content=entry.input["query"])]),
        config,
    )
    maybe_viz_message = find_last_message_of_type(state["messages"], ArtifactRefMessage)
    if maybe_viz_message:
        artifact_manager = ArtifactManager(team=team, user=eval_ctx.user, config=config)
        enriched_message = await artifact_manager.aget_enriched_message(maybe_viz_message)
        content = unwrap_visualization_artifact_content(enriched_message)
        if content is None:
            return EvalOutput(database_schema=database_schema)
        return EvalOutput(
            database_schema=database_schema,
            query_kind=content.query.kind,
            sql_query=content.query.query if isinstance(content.query, AssistantHogQLQuery) else None,
        )
    return EvalOutput(database_schema=database_schema, query_kind=None, sql_query=None)


@capture_score
async def sql_semantics_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    metric = SQLSemanticsCorrectness(client=get_eval_context().get_openai_client_for_tracing(input.trace_id))
    return await metric.eval_async(
        output.sql_query,
        expected=expected,
        input=input.input["query"],
        database_schema=output.database_schema,
    )


@capture_score
async def sql_syntax_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    metric = SQLSyntaxCorrectness()
    return await metric.eval_async(
        output.sql_query,
        expected=expected,
        input=input.input["query"],
        team=await Team.objects.aget(id=input.team_id),
        database_schema=output.database_schema,
    )


def generate_test_cases(eval_ctx: EvaluationContext):
    for entry in eval_ctx.dataset_inputs:
        metadata: EvalMetadata = {"team_id": entry.team_id}
        yield EvalCase(
            input=entry,
            expected=entry.expected["output"],
            metadata=cast(dict, metadata),
        )


@pytest.mark.django_db
async def eval_offline_sql(eval_ctx: EvaluationContext, pytestconfig):
    await MaxPrivateEval(
        experiment_name=eval_ctx.formatted_experiment_name,
        task=call_graph,
        scores=[sql_syntax_scorer, sql_semantics_scorer],
        data=generate_test_cases(eval_ctx),
        pytestconfig=pytestconfig,
    )
