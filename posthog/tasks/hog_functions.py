from typing import Optional

from django.core.management import call_command
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.action.action import Action
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
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

    for hog_function in affected_hog_functions:
        hog_function.filters = compile_filters_bytecode(hog_function.filters, hog_function.team, actions_by_id)
        hog_function.updated_at = timezone.now()

    updates = HogFunction.objects.bulk_update(affected_hog_functions, ["filters", "updated_at"])

    reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[str(hog_function.id) for hog_function in affected_hog_functions]
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
