from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
import temporalio
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
)
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes
from temporalio.service import RPCStatusCode

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_pause_schedule,
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    trigger_schedule,
    unpause_schedule,
    update_schedule,
)
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY, POSTHOG_ORG_ID_KEY, POSTHOG_TEAM_ID_KEY

from products.data_modeling.backend.models.node import Node
from products.data_modeling.backend.schedule import build_schedule_spec
from products.data_modeling.backend.tasks.cleanup_orphaned_schedules import cleanup_orphaned_saved_query_schedule

logger = structlog.get_logger(__name__)

# Temporal RPC status codes that indicate a transient transport/availability failure rather than
# a definite, application-level error. When we hit one of these during schedule deletion we hand
# off to a Celery retry task instead of failing the user-facing request.
_TRANSIENT_RPC_STATUS_CODES = frozenset(
    {
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.RESOURCE_EXHAUSTED,
        RPCStatusCode.ABORTED,
        RPCStatusCode.INTERNAL,
        RPCStatusCode.UNKNOWN,
    }
)

if TYPE_CHECKING:
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def get_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> Schedule:
    from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector

    inputs = RunWorkflowInputs(
        team_id=saved_query.team_id,
        select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0)],
    )

    interval = saved_query.sync_frequency_interval or timedelta(hours=24)
    spec = build_schedule_spec(
        entity_id=saved_query.id,
        interval=interval,
        team_timezone=saved_query.team.timezone,
    )

    return Schedule(
        action=ScheduleActionStartWorkflow(
            "data-modeling-run",
            asdict(inputs),
            id=str(saved_query.id),
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=2,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        ),
        spec=spec,
        state=ScheduleState(note=f"Schedule for saved query: {saved_query.pk}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.CANCEL_OTHER),
    )


def get_saved_query_search_attributes(saved_query: "DataWarehouseSavedQuery") -> TypedSearchAttributes:
    dag_id = Node.objects.filter(saved_query=saved_query).values_list("dag_id", flat=True).first()
    search_attributes: list[SearchAttributePair] = [
        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=saved_query.team_id),
        SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=str(saved_query.team.organization_id)),
    ]
    if dag_id:
        search_attributes.append(SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=str(dag_id)))
    return TypedSearchAttributes(search_attributes=search_attributes)


def sync_saved_query_workflow(
    saved_query: "DataWarehouseSavedQuery", create: bool = False
) -> "DataWarehouseSavedQuery":
    temporal = sync_connect()
    schedule = get_saved_query_schedule(saved_query)
    search_attributes = get_saved_query_search_attributes(saved_query)

    if create:
        create_schedule(
            temporal,
            id=str(saved_query.id),
            schedule=schedule,
            trigger_immediately=True,
            search_attributes=search_attributes,
        )
    else:
        update_schedule(temporal, id=str(saved_query.id), schedule=schedule, search_attributes=search_attributes)

    return saved_query


def delete_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    """Delete the Temporal schedule backing a saved query, tolerating transient transport failures.

    Called from `revert_materialization` *after* the DB revert has committed. A transient Temporal
    outage at this point would otherwise bubble up a 500 and orphan the schedule, so we hand off
    transient failures to a Celery retry task and let the user-facing flow continue.
    """
    schedule_id = str(saved_query.id)
    try:
        temporal = sync_connect()
        delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return
        if e.status in _TRANSIENT_RPC_STATUS_CODES:
            _enqueue_orphaned_schedule_cleanup(saved_query, exc=e)
            return
        raise
    except RuntimeError as e:
        # `Client.connect` raises a bare RuntimeError on DNS / transport failures rather than
        # an RPCError, so it would otherwise escape the handler above.
        _enqueue_orphaned_schedule_cleanup(saved_query, exc=e)
        return


def _enqueue_orphaned_schedule_cleanup(saved_query: "DataWarehouseSavedQuery", exc: BaseException) -> None:
    """Capture the transient failure and dispatch an async retry for the orphaned schedule."""
    capture_exception(
        exc,
        {
            "saved_query_id": str(saved_query.id),
            "team_id": saved_query.team_id,
        },
    )
    logger.warning(
        "delete_saved_query_schedule_transient_failure",
        saved_query_id=str(saved_query.id),
        team_id=saved_query.team_id,
        error=str(exc),
    )
    try:
        cleanup_orphaned_saved_query_schedule.apply_async(args=[str(saved_query.id)], countdown=30)
    except Exception as dispatch_exc:
        capture_exception(dispatch_exc, {"saved_query_id": str(saved_query.id)})
        logger.exception(
            "delete_saved_query_schedule_dispatch_failed",
            saved_query_id=str(saved_query.id),
        )


def pause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=str(saved_query.id))


async def a_pause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = await async_connect()
    await a_pause_schedule(temporal, schedule_id=str(saved_query.id))


def unpause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=str(saved_query.id))
    # reset the automatic sync interval for rev analytics
    viewset = saved_query.managed_viewset
    if viewset and viewset.kind == "revenue_analytics":
        previous_interval = saved_query.sync_frequency_interval
        new_interval = timedelta(hours=12)
        saved_query.sync_frequency_interval = new_interval
        saved_query.save()
        if previous_interval != new_interval:
            log_activity(
                organization_id=saved_query.team.organization_id,
                team_id=saved_query.team_id,
                user=None,
                was_impersonated=False,
                item_id=saved_query.id,
                scope="DataWarehouseSavedQuery",
                activity="sync_frequency_reset",
                detail=Detail(
                    name=saved_query.name,
                    changes=[
                        Change(
                            field="sync_frequency_interval",
                            action="changed",
                            type="DataWarehouseSavedQuery",
                            before=str(previous_interval) if previous_interval else None,
                            after=str(new_interval),
                        ),
                    ],
                ),
            )


def saved_query_workflow_exists(saved_query: "DataWarehouseSavedQuery") -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=str(saved_query.id))


def trigger_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id))
