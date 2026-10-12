"""Who an insight alert emails, for the production check and for the shared platform.

An insight alert emails its subscribed users besides any HogFunction destinations. Both senders
read recipients here, so a user who loses access to the insight stops receiving either.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final
from uuid import UUID

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    DestinationType,
)

# A failed check has no internal event of its own, because production emails it directly. The
# platform routes errored transitions to email by this id, which no HogFunction can subscribe to.
INSIGHT_ALERT_ERRORED_EVENT_ID: Final = "$insight_alert_errored"

SUBSCRIBER_EVENT_IDS: Final = frozenset({LEGACY_INSIGHT_ALERT_EVENT, INSIGHT_ALERT_ERRORED_EVENT_ID})


def insight_alert(*, team_id: int, alert_id: str) -> AlertConfiguration | None:
    """The insight alert a platform destination lookup names, or None when the id is another source's."""
    try:
        alert_uuid = UUID(alert_id)
    except ValueError:
        return None
    return AlertConfiguration.objects.filter(team_id=team_id, id=alert_uuid).select_related("team", "insight").first()


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
    return [
        (user.id, user.email)
        for user in candidates
        if UserAccessControl(user, team=alert.team).check_access_level_for_object(alert.insight, "viewer")
    ]


def insight_email_groups(recipients: Collection[tuple[int, str]]) -> list[AlertDestinationGroup]:
    addresses = sorted({email for _, email in recipients if email})
    if not addresses:
        return []
    data: AlertDestinationData = {"type": DestinationType.EMAIL, "email_addresses": addresses}
    return [AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=True)]
