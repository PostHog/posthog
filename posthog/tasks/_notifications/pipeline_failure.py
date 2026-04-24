from collections.abc import Sequence

import structlog

from posthog.models import OrganizationMembership, Team

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
