from collections.abc import Sequence

import structlog

from posthog.batch_exports.models import BatchExportRun
from posthog.models import OrganizationMembership, PluginConfig, Team
from posthog.models.utils import UUIDT
from posthog.tasks.email import get_members_to_notify_for_pipeline_error

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType

logger = structlog.get_logger(__name__)


def dispatch_pipeline_failure_realtime(
    *,
    team: Team,
    memberships: Sequence[OrganizationMembership],
    title: str,
    body: str,
    resource_id: str,
    source_url: str,
) -> None:
    """Fire one in-app pipeline_failure notification per membership.

    Wrapped in try/except per call so a single bad recipient doesn't drop the rest.
    Never raises — caller's email side-effect must always succeed independently.
    """
    title_truncated = title[:100]
    body_truncated = body[:200]
    for membership in memberships:
        try:
            create_notification(
                NotificationData(
                    team_id=team.id,
                    notification_type=NotificationType.PIPELINE_FAILURE,
                    priority=Priority.NORMAL,
                    title=title_truncated,
                    body=body_truncated,
                    target_type=TargetType.USER,
                    target_id=str(membership.user_id),
                    resource_type=NotificationOnlyResourceType.PIPELINE,
                    resource_id=resource_id,
                    source_url=source_url,
                )
            )
        except Exception as e:
            logger.exception(
                "pipeline_failure.realtime_failed",
                team_id=team.id,
                user_id=membership.user_id,
                error=str(e),
            )


def dispatch_plugin_disabled_realtime(plugin_config_id: int, error: str) -> None:
    """Fire realtime pipeline_failure notifications for a plugin that crashed.

    Loads the plugin/team/recipients from the DB and delegates to dispatch_pipeline_failure_realtime.
    Never raises.
    """
    try:
        plugin_config = PluginConfig.objects.prefetch_related("plugin", "team").get(id=plugin_config_id)
        team = plugin_config.team
        if team is None:
            return
        memberships = get_members_to_notify_for_pipeline_error(team, failure_rate=1.0)
        if not memberships:
            return
        dispatch_pipeline_failure_realtime(
            team=team,
            memberships=memberships,
            title=f"Plugin {plugin_config.plugin.name} disabled",
            body=error,
            resource_id=str(plugin_config_id),
            source_url=f"/project/{team.project_id}/pipeline/transformations/{plugin_config_id}",
        )
    except Exception as e:
        logger.exception("dispatch_plugin_disabled_realtime.failed", plugin_config_id=plugin_config_id, error=str(e))


def dispatch_batch_export_failure_realtime(batch_export_run_id: str | UUIDT, failure_rate: float = 1.0) -> None:
    """Fire realtime pipeline_failure notifications for a failed batch export run.

    Loads run/batch_export/team/recipients from the DB and delegates. Never raises.
    """
    try:
        batch_export_run = BatchExportRun.objects.select_related("batch_export__team").get(id=batch_export_run_id)
        team = batch_export_run.batch_export.team
        memberships = get_members_to_notify_for_pipeline_error(team, failure_rate)
        if not memberships:
            return
        dispatch_pipeline_failure_realtime(
            team=team,
            memberships=memberships,
            title=f"Batch export {batch_export_run.batch_export.name} failed",
            body=f"Last failure at {batch_export_run.last_updated_at.strftime('%I:%M%p %Z on %B %d')}",
            resource_id=str(batch_export_run.batch_export.id),
            source_url=f"/project/{team.project_id}/batch_exports/{batch_export_run.batch_export.id}",
        )
    except Exception as e:
        logger.exception(
            "dispatch_batch_export_failure_realtime.failed",
            batch_export_run_id=str(batch_export_run_id),
            error=str(e),
        )
