"""Who an alert emails besides its HogFunction destinations.

An insight alert emails its subscribed users. Both senders, the production check and the shared
platform, read recipients here, so a user who loses access to the insight stops receiving either.

Another source registers a resolver for the event ids it maps firing and resolved onto, and the
platform then emails the addresses that resolver returns for each alert. The source owns the
access rules, because only it knows who may read what its alerts say.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Final
from uuid import UUID

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.facade.contracts import AlertEmailRecipientResolver
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    DestinationType,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

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
    return email_groups(email for _, email in recipients)


def email_groups(addresses: Iterable[str]) -> list[AlertDestinationGroup]:
    # Sorted and deduplicated, because delivery tells destinations apart by their data. The same
    # people in another order would read as a second destination.
    unique = sorted({address for address in addresses if address})
    if not unique:
        return []
    data: AlertDestinationData = {"type": DestinationType.EMAIL, "email_addresses": unique}
    return [AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=True)]


_recipient_resolvers: dict[str, AlertEmailRecipientResolver] = {}


def register_recipient_resolver(*, event_ids: Collection[str], resolver: AlertEmailRecipientResolver) -> None:
    for event_id in event_ids:
        if event_id in SUBSCRIBER_EVENT_IDS:
            raise RuntimeError(f"{event_id} already emails the subscribers of an insight alert.")
        registered = _recipient_resolvers.get(event_id)
        # One owner per event. A second registrant would silently replace who the first one emails.
        if registered is not None and registered is not resolver:
            raise RuntimeError(f"A different email recipient resolver is already registered for {event_id}.")
    for event_id in event_ids:
        _recipient_resolvers[event_id] = resolver


def registered_email_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """One email group for the addresses that the resolvers of these events return for the alert."""
    resolvers = {
        id(resolver): resolver
        for event_id in allowed_event_ids
        if (resolver := _recipient_resolvers.get(event_id)) is not None
    }
    return email_groups(
        address for resolver in resolvers.values() for address in resolver(team_id=team_id, alert_id=alert_id)
    )
