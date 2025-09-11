from typing import Optional

from celery import shared_task
from structlog import get_logger

from posthog.tasks.email import send_fatal_plugin_error
from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)

# IMPORTANT - Do not modify this without also modifying plugin-server/../celery.ts
# Same goes for this file path and the task names
queue = CeleryQueue.DEFAULT.value


# Called from plugin-server/../lazy.ts
@shared_task(ignore_result=True, queue=queue)
def fatal_plugin_error(
    plugin_config_id: int,
    plugin_config_updated_at: Optional[str],
    error: str,
    is_system_error: bool,
) -> None:
    send_fatal_plugin_error.delay(plugin_config_id, plugin_config_updated_at, error, is_system_error)


# Called from plugin-server/../hog-watcher.service.ts
@shared_task(ignore_result=True, queue=queue)
def hog_function_state_transition(hog_function_id: str, state: int) -> None:
    logger.info("hog_function_state_transition (disabled)", hog_function_id=hog_function_id, state=state)
    return
    # from posthog.models.hog_functions.hog_function import HogFunction

    # logger.info("hog_function_state_transition", hog_function_id=hog_function_id, state=state)

    # hog_function = HogFunction.objects.get(id=hog_function_id)

    # if not hog_function:
    #     logger.warning("hog_function_state_transition: hog_function not found", hog_function_id=hog_function_id)
    #     return

    # report_team_action(
    #     hog_function.team,
    #     "hog function state changed",
    #     {
    #         "hog_function_id": hog_function_id,
    #         "hog_function_url": f"{settings.SITE_URL}/project/{hog_function.team.id}/pipeline/destinations/hog-{hog_function_id}",
    #         "state": state,
    #     },
    # )

    # # TRICKY: It seems like without this call the events don't get flushed, possibly due to celery worker threads exiting...
    # logger.info("hog_function_state_transition: Flushing posthoganalytics")
    # posthoganalytics.flush()

    # if state >= 2:  # 2 and 3 are disabled
    #     logger.info("hog_function_state_transition: sending hog_function_disabled email")
    #     send_hog_function_disabled.delay(hog_function_id)

    # logger.info("hog_function_state_transition: done")
