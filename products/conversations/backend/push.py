import structlog

from posthog.models import OrganizationMembership, Team

from products.notifications.backend.facade.api import publish_silent_push

logger = structlog.get_logger(__name__)

CONVERSATIONS_UNREAD_CHANGED = "conversations_unread_changed"


def push_unread_count_changed(team: Team) -> None:
    """Notify all org members via SSE that the conversations unread count changed."""
    org_id = team.organization_id
    if not org_id:
        return

    user_ids = list(OrganizationMembership.objects.filter(organization_id=org_id).values_list("user_id", flat=True))
    if not user_ids:
        return

    publish_silent_push(
        organization_id=str(org_id),
        team_id=team.pk,
        event_type=CONVERSATIONS_UNREAD_CHANGED,
        user_ids=user_ids,
    )
