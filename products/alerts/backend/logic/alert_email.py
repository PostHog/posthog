"""Who an insight alert the insight stack owns emails besides its HogFunction destinations: its
subscribed users who can still view the insight. The platform reads an alert it owns from the
alert's subscriber destinations instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.models.alert import AlertConfiguration

if TYPE_CHECKING:
    from posthog.models import User

# A failed check has no internal event of its own, because production emails it directly. The
# platform routes errored transitions to email by this id, which no HogFunction can subscribe to.
INSIGHT_ALERT_ERRORED_EVENT_ID: Final = "$insight_alert_errored"


def alert_email_recipients(*, team_id: int, alert_id: UUID) -> list[tuple[int, str]]:
    """Subscribed users who can still view the project and the alert's insight."""
    alert = AlertConfiguration.objects.filter(team_id=team_id, id=alert_id).select_related("team", "insight").first()
    return recipients_with_access(alert) if alert is not None else []


def recipients_with_access(alert: AlertConfiguration) -> list[tuple[int, str]]:
    candidates = (
        alert.team.all_users_with_access()
        .filter(id__in=alert.subscribed_users.values_list("id", flat=True))
        .only("id", "email")
    )
    return [(user.id, user.email) for user in candidates if can_view_insight(user, alert)]


def can_view_insight(user: User, alert: AlertConfiguration) -> bool:
    return UserAccessControl(user, team=alert.team).check_access_level_for_object(alert.insight, "viewer")
