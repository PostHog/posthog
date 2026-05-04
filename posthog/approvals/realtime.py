from typing import TYPE_CHECKING

from structlog import get_logger

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


def dispatch_approval_resolved_realtime(change_request: "ChangeRequest", *, title: str, body: str) -> None:
    if not change_request.created_by_id:
        return
    try:
        create_notification(
            NotificationData(
                team_id=change_request.team_id,
                notification_type=NotificationType.APPROVAL_RESOLVED,
                priority=Priority.NORMAL,
                title=title[:100],
                body=body[:200],
                target_type=TargetType.USER,
                target_id=str(change_request.created_by_id),
                resource_type=NotificationOnlyResourceType.APPROVAL,
                resource_id=str(change_request.id),
                source_url=f"/project/{change_request.team.project_id}/approvals/{change_request.id}",
            )
        )
    except Exception as e:
        logger.exception(
            "send_approval_resolved_notification.realtime_failed",
            change_request_id=str(change_request.id),
            error=str(e),
        )
