import time
import asyncio
import hashlib
from datetime import datetime, timedelta

from django.conf import settings

import structlog
from celery import shared_task
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Cap backfill to avoid overwhelming the system on resume
MAX_BACKFILL_EVENTS = 10_000


def _check_rollout_percentage(event_uuid: str, rollout_percentage: float) -> bool:
    """Deterministic sampling matching the plugin server's MD5-based approach."""
    if rollout_percentage >= 100:
        return True
    hash_hex = hashlib.md5(event_uuid.encode()).hexdigest()  # noqa: S324
    hash_value = int(hash_hex[:8], 16)
    percentage = (hash_value % 10000) / 100
    return percentage < rollout_percentage


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def backfill_paused_evaluation_events(evaluation_id: str, team_id: int, paused_at_iso: str) -> None:
    """Backfill events that were missed while an evaluation was paused.

    Queries ClickHouse for $ai_generation events since the evaluation was
    paused, applies the evaluation's condition rollout percentages, then
    dispatches Temporal workflows for matching events.
    """
    from posthog.hogql import ast
    from posthog.hogql.property import property_to_expr
    from posthog.hogql.query import execute_hogql_query

    from posthog.models.team import Team
    from posthog.temporal.common.client import sync_connect
    from posthog.temporal.llm_analytics.run_evaluation import RunEvaluationInputs

    from products.llm_analytics.backend.models.evaluations import Evaluation

    try:
        evaluation = Evaluation.objects.get(id=evaluation_id, team_id=team_id, deleted=False)
    except Evaluation.DoesNotExist:
        logger.warning("Evaluation not found for backfill", evaluation_id=evaluation_id, team_id=team_id)
        return

    team = Team.objects.get(id=team_id)
    paused_at = datetime.fromisoformat(paused_at_iso)
    conditions = evaluation.conditions or []

    if not conditions:
        logger.info("No conditions on evaluation, skipping backfill", evaluation_id=evaluation_id)
        return

    # Build HogQL WHERE clause from conditions (OR between condition sets)
    condition_exprs: list[ast.Expr] = []
    for condition in conditions:
        props = condition.get("properties", [])
        if props:
            condition_exprs.append(property_to_expr(props, team))
        else:
            condition_exprs.append(ast.Constant(value=True))

    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value="$ai_generation"),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=paused_at),
        ),
    ]

    if len(condition_exprs) == 1:
        where_exprs.append(condition_exprs[0])
    else:
        where_exprs.append(ast.Or(exprs=condition_exprs))

    query = ast.SelectQuery(
        select=[
            ast.Field(chain=["uuid"]),
            ast.Field(chain=["event"]),
            ast.Field(chain=["properties"]),
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["distinct_id"]),
            ast.Field(chain=["elements_chain"]),
            ast.Field(chain=["created_at"]),
            ast.Field(chain=["person_id"]),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=where_exprs),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit=ast.Constant(value=MAX_BACKFILL_EVENTS),
    )

    response = execute_hogql_query(query=query, team=team, limit_context=None)

    if not response.results:
        logger.info("No events to backfill", evaluation_id=evaluation_id, team_id=team_id)
        return

    # Build event dicts from HogQL results, applying rollout percentage
    columns = response.columns or [
        "uuid",
        "event",
        "properties",
        "timestamp",
        "distinct_id",
        "elements_chain",
        "created_at",
        "person_id",
    ]
    matching_events = []
    for row in response.results:
        event_data = dict(zip(columns, row))
        event_uuid = str(event_data.get("uuid", ""))
        event_data["team_id"] = team_id

        for condition in conditions:
            rollout_pct = condition.get("rollout_percentage", 100)
            if _check_rollout_percentage(event_uuid, rollout_pct):
                matching_events.append(event_data)
                break

    if not matching_events:
        logger.info("No events matched rollout after filtering", evaluation_id=evaluation_id)
        return

    logger.info(
        "Backfilling paused evaluation",
        evaluation_id=evaluation_id,
        team_id=team_id,
        total_events=len(response.results),
        matching_events=len(matching_events),
        paused_at=paused_at_iso,
    )

    client = sync_connect()
    prefix = "llma-hog-eval" if evaluation.evaluation_type == "hog" else "llma-llm-eval"

    async def _dispatch_all() -> int:
        count = 0
        for event_data in matching_events:
            event_uuid = str(event_data.get("uuid", ""))
            workflow_id = f"{prefix}-{evaluation_id}-{event_uuid}-backfill-{int(time.time() * 1000)}"

            inputs = RunEvaluationInputs(
                evaluation_id=str(evaluation_id),
                event_data=event_data,
            )

            try:
                await client.start_workflow(
                    "run-evaluation",
                    inputs,
                    id=workflow_id,
                    task_queue=settings.LLMA_EVALS_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    task_timeout=timedelta(minutes=2),
                )
                count += 1
            except Exception:
                logger.exception(
                    "Failed to dispatch backfill workflow",
                    evaluation_id=evaluation_id,
                    event_uuid=event_uuid,
                )
        return count

    dispatched = asyncio.run(_dispatch_all())

    logger.info(
        "Backfill complete",
        evaluation_id=evaluation_id,
        team_id=team_id,
        dispatched=dispatched,
        total_matching=len(matching_events),
    )
