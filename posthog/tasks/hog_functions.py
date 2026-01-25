from typing import Optional

from django.core.management import call_command
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.hogql.query import execute_hogql_query

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.plugins.plugin_server_api import create_hog_invocation_test, reload_hog_functions_on_workers
from posthog.redis import get_client
from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_affected_hog_functions(team_id: Optional[int] = None, action_id: Optional[int] = None) -> int:
    from posthog.models.hog_functions.hog_function import HogFunction

    affected_hog_functions: list[HogFunction] = []

    if action_id:
        action = Action.objects.get(id=action_id)
        team_id = action.team_id
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=action.team_id)
            .filter(filters__contains={"actions": [{"id": str(action_id)}]})
        )
    elif team_id:
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=team_id)
            .filter(filters__contains={"filter_test_accounts": True})
        )

    if team_id is None:
        raise Exception("Either team_id or action_id must be provided")

    if not affected_hog_functions:
        return 0

    all_related_actions = (
        Action.objects.select_related("team")
        .filter(team_id=team_id)
        .filter(
            id__in=[
                action_id for hog_function in affected_hog_functions for action_id in hog_function.filter_action_ids
            ]
        )
    )

    actions_by_id = {action.id: action for action in all_related_actions}

    successfully_compiled_hog_functions = []
    for hog_function in affected_hog_functions:
        compiled_filters = compile_filters_bytecode(hog_function.filters, hog_function.team, actions_by_id)

        # Only update if compilation succeeded (no bytecode_error)
        if not compiled_filters.get("bytecode_error"):
            hog_function.filters = compiled_filters
            hog_function.updated_at = timezone.now()
            successfully_compiled_hog_functions.append(hog_function)
        else:
            logger.warning(
                f"Failed to compile filters for hog function {hog_function.id}: {compiled_filters.get('bytecode_error')}. "
                "Keeping existing filters intact."
            )

    updates = HogFunction.objects.bulk_update(successfully_compiled_hog_functions, ["filters", "updated_at"])

    reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[str(hog_function.id) for hog_function in successfully_compiled_hog_functions]
    )

    return updates


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=5,
    default_retry_delay=30,  # retry every 30 seconds
)
def sync_hog_function_templates_task() -> None:
    try:
        logger.info("Running sync_hog_function_templates command (celery task)...")
        call_command("sync_hog_function_templates")
    except Exception as e:
        logger.exception(f"Celery task sync_hog_function_templates failed: {e}")
        raise  # Needed for Celery to trigger a retry


def queue_sync_hog_function_templates() -> None:
    """Queue the sync_hog_function_templates_task with Redis lock to ensure it only runs once."""
    try:
        r = get_client()
        lock_key = "posthog_sync_hog_function_templates_task_lock"
        # setnx returns True if the key was set, False if it already exists
        if r.setnx(lock_key, 1):
            r.expire(lock_key, 60 * 60)  # expire after 1 hour
            logger.info("Queuing sync_hog_function_templates celery task (redis lock)...")
            sync_hog_function_templates_task.delay()
        else:
            logger.info("Not queuing sync_hog_function_templates task: lock already set")
    except Exception as e:
        logger.exception(f"Failed to queue sync_hog_function_templates celery task: {e}")


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def batch_retry_hog_function(
    team_id: int, hog_function_id: str, date_from: str, date_to: str, status: str = "error", batch_size: int = 20
) -> int:
    try:
        from posthog.models.team import Team

        team = Team.objects.get(id=team_id)

        # 1. Fetch failing invocations from ClickHouse
        query = """
            SELECT message, instance_id
            FROM log_entries
            WHERE team_id = {team_id}
            AND log_source = 'hog_function'
            AND log_source_id = {hog_function_id}
            AND timestamp >= toDateTime({date_from})
            AND timestamp <= toDateTime({date_to})
            AND level = {status}
            AND (message like '%Error executing function on event%' OR message like '%messages failed%')
            LIMIT 1000
        """

        response = execute_hogql_query(
            query_type="HogQLQuery",
            query=query,
            values={
                "team_id": team_id,
                "hog_function_id": hog_function_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": status,
            },
            team=team,
        )

        import re

        event_id_matchers = [
            re.compile(r"Event: ([A-Za-z0-9-]+)"),
            re.compile(r"\/events\/([A-Za-z0-9-]+)\/"),
            re.compile(r"event ([A-Za-z0-9-]+)"),
        ]

        event_ids = set()

        for row in response.results or []:
            message = row[0]
            for matcher in event_id_matchers:
                match = matcher.search(message)
                if match:
                    event_ids.add(match.group(1))
                    break

        if not event_ids:
            logger.warning(
                f"Found {len(response.results or [])} failed logs for HogFunction {hog_function_id}, "
                "but failed to extract any event IDs. Check regex matchers."
            )
            return 0

        event_id_list = list(event_ids)

        hog_function = HogFunction.objects.get(id=hog_function_id, team_id=team_id)

        total_triggered = 0

        for i in range(0, len(event_id_list), batch_size):
            batch_ids = event_id_list[i : i + batch_size]

            events_query = """
                SELECT uuid, distinct_id, event, timestamp, properties, elements_chain, person.id, person.properties, person.created_at
                FROM events
                WHERE uuid IN {batch_ids}
                AND team_id = {team_id}
            """

            events_res = execute_hogql_query(
                query_type="HogQLQuery",
                query=events_query,
                values={
                    "batch_ids": batch_ids,
                    "team_id": team_id,
                },
                team=team,
            )

            for event_row in events_res.results or []:
                clickhouse_event = {
                    "uuid": event_row[0],
                    "distinct_id": event_row[1],
                    "event": event_row[2],
                    "timestamp": event_row[3],
                    "properties": event_row[4],
                    "elements_chain": event_row[5],
                    "person_id": event_row[6],
                    "person_properties": event_row[7],
                    "person_created_at": event_row[8],
                }

                # Payload matching HogFunctionInvocationSerializer
                payload = {
                    "configuration": {
                        "id": hog_function.id,
                        "type": hog_function.type,
                        "hog": hog_function.hog,
                        "inputs": hog_function.inputs or {},
                    },
                    "clickhouse_event": clickhouse_event,
                    "mock_async_functions": False,
                    "invocation_id": f"retry-{event_row[0]}",
                }

                config_data = {
                    "id": hog_function.id,
                    "team_id": team_id,
                    "name": hog_function.name,
                    "type": hog_function.type,
                    "hog": hog_function.hog,
                    "inputs": hog_function.inputs,
                    "encrypted_inputs": hog_function.encrypted_inputs,
                    "filters": hog_function.filters,
                    "enabled": True,  # Force enable for test
                }

                payload["configuration"] = config_data

                try:
                    create_hog_invocation_test(team_id=team_id, hog_function_id=str(hog_function_id), payload=payload)
                    total_triggered += 1
                except Exception as e:
                    logger.exception(f"Failed to retry invocation for event {clickhouse_event['uuid']}: {e}")

        return total_triggered

    except Exception as e:
        logger.exception(f"Batch retry hog function failed: {e}")
        raise
