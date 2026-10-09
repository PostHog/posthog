"""Who an insight alert notifies in the app, for the shared platform.

The production check notifies subscribers in the app besides any HogFunction destinations. The
recipients here are the ones production chooses for each kind, so a pilot alert reaches the same
inboxes on both paths.
"""

from __future__ import annotations

from collections.abc import Collection

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT

from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    DestinationType,
)


def insight_in_app_groups(
    alert: AlertConfiguration, *, event_ids: Collection[str], recipients_with_access: Collection[tuple[int, str]]
) -> list[AlertDestinationGroup]:
    short_id = alert.insight.short_id
    groups: list[AlertDestinationGroup] = []
    if LEGACY_INSIGHT_ALERT_EVENT in event_ids:
        # Production notifies every subscriber of a firing and leaves the access check to the
        # inbox, which checks access to insights in general and not to this insight.
        firing_user_ids = list(alert.subscribed_users.values_list("id", flat=True))
        if firing_user_ids:
            groups.append(
                _group(
                    user_ids=firing_user_ids,
                    short_id=short_id,
                    url=f"/project/{alert.team.project_id}/insights/{short_id}#alert={alert.id}",
                )
            )
    if INSIGHT_ALERT_ERRORED_EVENT_ID in event_ids and recipients_with_access:
        groups.append(
            _group(
                user_ids=[user_id for user_id, _ in recipients_with_access],
                short_id=short_id,
                url=f"/project/{alert.team_id}/insights/{short_id}?alert_id={alert.id}",
            )
        )
    return groups


def _group(*, user_ids: list[int], short_id: str, url: str) -> AlertDestinationGroup:
    data: AlertDestinationData = {
        "type": DestinationType.IN_APP,
        "in_app_user_ids": sorted(user_ids),
        "in_app_resource_type": "insight",
        "in_app_resource_id": short_id,
        "in_app_url": url,
    }
    return AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=True)
