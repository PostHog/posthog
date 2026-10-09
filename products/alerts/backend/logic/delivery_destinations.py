"""Everything the shared platform delivers one alert's events to."""

from __future__ import annotations

from collections.abc import Collection

from products.alerts.backend.logic.alert_email import insight_email_group
from products.alerts.backend.logic.alert_in_app import insight_in_app_groups
from products.alerts.backend.logic.destinations import list_alert_destination_groups
from products.alerts_platform.backend.facade.contracts import AlertDestinationGroup


def list_delivery_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """An alert's HogFunction destinations, plus its subscribers' email and in-app notifications
    for an insight alert.

    Separate from `list_alert_destination_groups`, which the alert APIs list and delete through. A
    subscriber group there would show up as a destination a person could delete.
    """
    groups = list_alert_destination_groups(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
    email = insight_email_group(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
    in_app = insight_in_app_groups(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
    return [*groups, *([email] if email is not None else []), *in_app]
