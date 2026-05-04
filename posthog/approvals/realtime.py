from typing import TYPE_CHECKING

from structlog import get_logger

from posthog.approvals.notifications import get_user_display_name

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType

if TYPE_CHECKING:
    from posthog.approvals.models import ChangeRequest

logger = get_logger(__name__)


def dispatch_approval_requested_realtime(change_request: "ChangeRequest") -> None:
    """Fan out one in-app notification per approver. Mirrors the email path's recipient resolution.

    Each approver dispatch is isolated in its own try/except so one failure does not block
    notifications for the remaining approvers.
    """
    policy = change_request.get_policy()
    if not policy:
        return
    approver_ids = policy.get_approver_user_ids()
    if not approver_ids:
        return
    requester_name = get_user_display_name(change_request.created_by)
    title = f"{requester_name} needs your sign-off"[:100]
    body = f"Action: {change_request.action_key}"[:200]
    source_url = f"/project/{change_request.team.project_id}/approvals/{change_request.id}"
    for approver_id in approver_ids:
        try:
            create_notification(
                NotificationData(
                    team_id=change_request.team_id,
                    notification_type=NotificationType.APPROVAL_REQUESTED,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.USER,
                    target_id=str(approver_id),
                    resource_type=NotificationOnlyResourceType.APPROVAL,
                    resource_id=str(change_request.id),
                    source_url=source_url,
                )
            )
        except Exception as e:
            logger.exception(
                "dispatch_approval_requested_realtime.failed",
                change_request_id=str(change_request.id),
                approver_id=str(approver_id),
                error=str(e),
            )
