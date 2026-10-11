from typing import Optional

from celery import shared_task
from structlog import get_logger

from posthog.tasks.email import get_members_to_notify_for_pipeline_error, send_fatal_plugin_error
from posthog.tasks.utils import CeleryQueue

from products.cdp.backend.models.plugin import PluginConfig
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
    has_been_dispatched,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType

logger = get_logger(__name__)

# IMPORTANT - Do not modify this without also modifying plugin-server/../celery.ts
# Same goes for this file path and the task names
queue = CeleryQueue.DEFAULT.value


def _dispatch_plugin_disabled_realtime(
    plugin_config_id: int,
    plugin_config_updated_at: Optional[str],
    error: str,
) -> None:
    """Fire one realtime pipeline_failure notification per pipeline-error recipient.

    Per-recipient try/except so one bad write does not drop the rest. Never raises so
    a realtime failure cannot poison the email side-effect. Per-recipient idempotency keyed
    on plugin_config_updated_at matches the email path's MessagingRecord dedup, so the
    same disable event won't double-notify on Celery retries or racing workers.
    """
    try:
        plugin_config = PluginConfig.objects.select_related("plugin", "team").get(id=plugin_config_id)
        team = plugin_config.team
        if team is None:
            return
        # failure_rate=1.0 mirrors the email path (send_fatal_plugin_error) — a disabled plugin
        # is treated as 100% failure, so users are filtered only by their data_pipeline_error_threshold.
        memberships = get_members_to_notify_for_pipeline_error(team, failure_rate=1.0)
        if not memberships:
            return
        title = f"Plugin {plugin_config.plugin.name} disabled"[:100]
        body = error[:200]
        source_url = f"/project/{team.project_id}/pipeline/plugins/{plugin_config_id}"
        source_id = str(plugin_config_updated_at) if plugin_config_updated_at else ""
        for membership in memberships:
            target_id = str(membership.user_id)
            if has_been_dispatched(
                notification_type=NotificationType.PIPELINE_FAILURE,
                target_type=TargetType.USER,
                target_id=target_id,
                resource_id=str(plugin_config_id),
                source_id=source_id,
            ):
                continue
            try:
                create_notification(
                    NotificationData(
                        team_id=team.id,
                        notification_type=NotificationType.PIPELINE_FAILURE,
                        priority=Priority.NORMAL,
                        title=title,
                        body=body,
                        target_type=TargetType.USER,
                        target_id=target_id,
                        resource_type=NotificationOnlyResourceType.PIPELINE,
                        resource_id=str(plugin_config_id),
                        source_url=source_url,
                        source_id=source_id,
                    )
                )
            except Exception as e:
                logger.exception(
                    "fatal_plugin_error.realtime_failed",
                    plugin_config_id=plugin_config_id,
                    user_id=membership.user_id,
                    error=str(e),
                )
    except Exception as e:
        logger.exception("fatal_plugin_error.realtime_setup_failed", plugin_config_id=plugin_config_id, error=str(e))


# Called from plugin-server/../lazy.ts
@shared_task(ignore_result=True, queue=queue)
def fatal_plugin_error(
    plugin_config_id: int,
    plugin_config_updated_at: Optional[str],
    error: str,
    is_system_error: bool,
) -> None:
    send_fatal_plugin_error.delay(plugin_config_id, plugin_config_updated_at, error, is_system_error)
    _dispatch_plugin_disabled_realtime(plugin_config_id, plugin_config_updated_at, error)


# Called from plugin-server/../hog-watcher.service.ts
@shared_task(ignore_result=True, queue=queue)
def hog_function_state_transition(hog_function_id: str, state: int) -> None:
    logger.info("hog_function_state_transition (disabled)", hog_function_id=hog_function_id, state=state)
    return
    # from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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
