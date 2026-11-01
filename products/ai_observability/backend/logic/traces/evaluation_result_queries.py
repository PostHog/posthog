from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ...models.evaluations import Evaluation
from .trace_queries import canonical_uuid

EVALUATION_RESULTS_LIMIT = 250


@frozen
class EvaluationResultRow:
    uuid: str
    timestamp: datetime
    evaluation_id: str | None
    evaluation_name: str | None
    target_event_id: str | None
    result: str | None
    reasoning: str | None
    applicable: str | None
    evaluation_type: str | None
    result_type: str | None
    sentiment_label: str | None
    skipped: str | None
    score: str | None
    categories: str | None
    backfill_id: str | None
    start_time: str | None


_PROPERTY_COLUMNS = {
    "evaluation_id": "$ai_evaluation_id",
    "evaluation_name": "$ai_evaluation_name",
    "target_event_id": "$ai_target_event_id",
    "result": "$ai_evaluation_result",
    "reasoning": "$ai_evaluation_reasoning",
    "applicable": "$ai_evaluation_applicable",
    "evaluation_type": "$ai_evaluation_runtime",
    "result_type": "$ai_evaluation_result_type",
    "sentiment_label": "$ai_sentiment_label",
    "skipped": "$ai_evaluation_skipped",
    "score": "$ai_evaluation_numeric_result",
    "categories": "$ai_evaluation_categorical_result",
    "backfill_id": "$ai_evaluation_backfill_id",
    "start_time": "$ai_evaluation_start_time",
}


def _equals(left: ast.Expr, value: str) -> ast.Expr:
    return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=left, right=ast.Constant(value=value))


def _results_query(trace_id: str) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["uuid"]),
            ast.Field(chain=["timestamp"]),
            *(ast.Field(chain=["properties", name]) for name in _PROPERTY_COLUMNS.values()),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                _equals(ast.Field(chain=["event"]), "$ai_evaluation"),
                _equals(ast.Field(chain=["properties", "$ai_trace_id"]), trace_id),
            ]
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=EVALUATION_RESULTS_LIMIT),
    )


def _raw(value: Any) -> str | None:
    # A property with a Boolean definition reads as a Python bool, so it is written the way untyped JSON reads.
    if isinstance(value, bool):
        return "true" if value else "false"
    return None if value is None else str(value)


def _result_row(values: Sequence[Any]) -> EvaluationResultRow:
    uuid, timestamp, *properties = values
    return EvaluationResultRow(
        uuid=str(uuid),
        timestamp=timestamp,
        **{field: _raw(value) for field, value in zip(_PROPERTY_COLUMNS, properties, strict=True)},
    )


def load_evaluation_results(team: Team, user: User | None, trace_id: str) -> tuple[EvaluationResultRow, ...]:
    name = "ai_trace_evaluation_results"
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=_results_query(trace_id),
            team=team,
            user=user,
            query_type=name,
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
        )
    return tuple(_result_row(values) for values in response.results or [])


def load_output_configs(
    team: Team, user: User | None, evaluation_ids: Iterable[str]
) -> dict[str, Mapping[str, object]]:
    """Keyed by each id as given, not by its canonical UUID form."""
    # Results can come from outside PostHog with any id, and a malformed UUID in the lookup raises.
    ids_by_uuid = {uuid: evaluation_id for evaluation_id in evaluation_ids if (uuid := canonical_uuid(evaluation_id))}
    if not ids_by_uuid:
        return {}
    # A deleted detector's results still read as a detector's, so deleted evaluations stay in.
    evaluations: QuerySet[Evaluation] = Evaluation.objects.filter(team_id=team.pk, id__in=ids_by_uuid)
    if user is not None:
        # Evaluations have their own access control, apart from the llm_analytics access that opens the trace.
        evaluations = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(
            evaluations, resource="evaluation"
        )
    rows = evaluations.values_list("id", "output_config")
    return {
        ids_by_uuid[str(evaluation_id)]: output_config
        for evaluation_id, output_config in rows
        if isinstance(output_config, Mapping)
    }
