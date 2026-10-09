"""Who an insight alert notifies in the app, for the shared platform.

An insight alert notifies its subscribers in the app besides any HogFunction destinations. Only
subscribers who can still view the alert's insight receive one, because the notification inbox
checks access to insights in general and not to one insight. The recipients are the email
recipients, so a user who loses access to the insight stops receiving either.
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
    user_ids = [user_id for user_id, _ in recipients_with_access]
    if not user_ids:
        return []
    short_id = alert.insight.short_id
    # Each kind links where the production notification for that kind links.
    urls = {
        LEGACY_INSIGHT_ALERT_EVENT: f"/project/{alert.team.project_id}/insights/{short_id}#alert={alert.id}",
        INSIGHT_ALERT_ERRORED_EVENT_ID: f"/project/{alert.team_id}/insights/{short_id}?alert_id={alert.id}",
    }
    return [
        _group(user_ids=user_ids, short_id=short_id, url=url) for event_id, url in urls.items() if event_id in event_ids
    ]


def _group(*, user_ids: list[int], short_id: str, url: str) -> AlertDestinationGroup:
    data: AlertDestinationData = {
        "type": DestinationType.IN_APP,
        "in_app_user_ids": sorted(user_ids),
        "in_app_resource_type": "insight",
        "in_app_resource_id": short_id,
        "in_app_url": url,
    }
    return AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=True)
