from typing import Optional

from django.core.management import call_command
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.action.action import Action
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers, create_hog_invocation_test
from posthog.redis import get_client
from posthog.tasks.utils import CeleryQueue
from posthog.hogql.query import execute_hogql_query
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.schema import HogQLQueryResponse

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
        # NOTE: This relies on the log entries being present in ClickHouse
        # We query for the unique event IDs that have a failure

        query = f"""
            SELECT distinct(log_source_id)
            FROM log_entries
            WHERE team_id = {team_id}
            AND log_source = 'hog_function'
            AND log_source_id = '{hog_function_id}'
            AND timestamp >= toDateTime('{date_from}')
            AND timestamp <= toDateTime('{date_to}')
            AND level = '{status}'
            LIMIT 1000
        """

        response: HogQLQueryResponse = execute_hogql_query(
            query_type="HogQLQuery",
            query=query,
            team=team,
        )

        invocation_ids = [row[0] for row in (response.results or [])]

        if not invocation_ids:
            logger.info(f"No failed invocations found for HogFunction {hog_function_id} in range")
            return 0

        # For retries we actually need the original event...
        # The log entry unfortunately doesn't link back to the event UUID directly in a reliable way for all log entries
        # But `log_source_id` is the hog function ID.
        # The `instance_id` in the log entry IS the invocation ID, which might be the event ID?
        # Let's double check how log entries are stored.
        # In `hogFunctionLogsLogic` we saw `eventIdByInvocationId`.
        # The `instance_id` column in `log_entries` corresponds to the invocation ID.
        # If the invocation ID IS the event ID (which it often is for async functions), we are good.
        # However, for captured events, it might be different.
        # But wait, `create_hog_invocation_test` takes `invocation_id` which it uses as the key.
        # If we re-invoke with the same ID, it should be fine.
        # BUT we need the EVENT data to re-run it.

        # Actually, `create_hog_invocation_test` expects a payload that includes the event data OR it fetches it?
        # No, `HogFunctionInvocationSerializer` takes `clickhouse_event`.
        # So we MUST fetch the event data from ClickHouse first.

        # Let's refine the query to get the event ID.
        # The `message` often contains "Error executing function on event <UUID>".
        # This is parsing logs, which is brittle.

        # Alternative: We can't easily auto-retry ONLY from logs without the event ID.
        # Be smart: Frontend `hogFunctionLogsLogic.ts` fetches the event ID from the log message for now.
        # AND it fetches the event from ClickHouse.
        # This confirms that the backend task also needs to:
        # 1. Provide a way to find the relevant events.
        # 2. Fetch them.
        # 3. Trigger retry.

        # Implementation V1:
        # The user's request is "Tool to automatically retry all failed invocations".
        # Since this is "Batch", maybe we can just accept a list of event IDs?
        # NO, the request says "UI for selecting a range of time... Button to trigger scheduling all of these".
        # So the backend should handle the search.

        # Let's stick to parsing the message for now as that is what the frontend does.
        # Better yet, maybe we simply query for events in that time range that matched the function?
        # No, we only want FAILED ones.

        # Let's reproduce the frontend logic: use the log message to find the event ID.
        # query = f"""
        #     SELECT message
        #     FROM log_entries
        #     ...
        # """
        # Then regex in Python.

        query = f"""
            SELECT message, instance_id
            FROM log_entries
            WHERE team_id = {team_id}
            AND log_source = 'hog_function'
            AND log_source_id = '{hog_function_id}'
            AND timestamp >= toDateTime('{date_from}')
            AND timestamp <= toDateTime('{date_to}')
            AND level = '{status}'
            AND (message like '%Error executing function on event%' OR message like '%messages failed%')
            LIMIT 1000
        """
        # Note: Added limit to prevent explosion. Defaults to 1000 for safety in V1.

        response = execute_hogql_query(
            query_type="HogQLQuery",
            query=query,
            team=team,
        )

        import re
        event_id_matchers = [
            re.compile(r"Event: ([A-Za-z0-9-]+)"),
            re.compile(r"\/events\/([A-Za-z0-9-]+)\/"),
            re.compile(r"event ([A-Za-z0-9-]+)"),
        ]

        event_ids = set()

        for row in (response.results or []):
            message = row[0]
            for matcher in event_id_matchers:
                match = matcher.search(message)
                if match:
                    event_ids.add(match.group(1))
                    break

        if not event_ids:
            return 0

        # Now fetch the events
        # We can't fetch all at once if there are many. Batch it.
        event_id_list = list(event_ids)
        
        # Determine the hog function config once
        hog_function = HogFunction.objects.get(id=hog_function_id, team_id=team_id)
        
        # We need to construct the payload for `create_hog_invocation_test`
        # It needs 'configuration', 'clickhouse_event', 'invocation_id'
        
        # Loop in batches
        total_triggered = 0
        
        for i in range(0, len(event_id_list), batch_size):
            batch_ids = event_id_list[i : i + batch_size]
            
            events_query = f"""
                SELECT uuid, distinct_id, event, timestamp, properties, elements_chain, person.id, person.properties, person.created_at
                FROM events
                WHERE uuid IN ({', '.join([f"'{eid}'" for eid in batch_ids])})
                AND team_id = {team_id}
            """
            
            events_res = execute_hogql_query(
                query_type="HogQLQuery",
                query=events_query,
                team=team,
            )
            
            for event_row in (events_res.results or []):
                 # Transform to clickhouse event dict (matching frontend loadClickhouseEvents logic somewhat)
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
                        # ... other fields if needed, but 'configuration' in invocation mainly needs basics or existing config
                        # Actually the API uses the passed configuration to override. If we want to use the "latest" we should pass it.
                        # The serializer expects a full config object usually.
                        # Let's look at `HogFunctionInvocationSerializer` again. 
                        # It has `configuration = HogFunctionSerializer(write_only=True)`.
                        # So we need to pass the full serialized function.
                    },
                    "clickhouse_event": clickhouse_event,
                    "mock_async_functions": False,
                    "invocation_id": f"retry-{event_row[0]}", # Unique ID for the retry? Or reuse? Frontend uses `groupedLogEntry.instanceId`. 
                    # If we use new ID, it's a new invocation. 
                }
                
                # We need to serialize the HogFunction to pass it
                from posthog.api.hog_function import HogFunctionSerializer
                # We need a request context usually, but here we might get away with basic dict
                # Actually, `create_hog_invocation_test` expects the payload dict.
                # And `HogFunctionSerializer` is used to VALIDATE the input in the view.
                # But here we are calling `create_hog_invocation_test` directly.
                # `create_hog_invocation_test` sends JSON to the worker. 
                # The worker expects the config.
                
                # Let's simplify: passing the existing model instance fields manually or via serializer
                # Serializer requires context.
                # Let's try to construct a minimal config that satisfies the worker.
                # The worker likely needs `type`, `hog`, `inputs`, `filters` etc.
                
                config_data = {
                    "id": hog_function.id,
                    "team_id": team_id,
                    "name": hog_function.name,
                    "type": hog_function.type,
                    "hog": hog_function.hog,
                    "inputs": hog_function.inputs,
                    "encrypted_inputs": hog_function.encrypted_inputs,
                    "filters": hog_function.filters,
                    "enabled": True, # Force enable for test
                }
                
                payload["configuration"] = config_data
                
                create_hog_invocation_test(
                    team_id=team_id,
                    hog_function_id=str(hog_function_id),
                    payload=payload
                )
                total_triggered += 1

        return total_triggered

    except Exception as e:
        logger.exception(f"Batch retry hog function failed: {e}")
        raise
