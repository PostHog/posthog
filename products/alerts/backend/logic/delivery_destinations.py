"""Everything the shared platform delivers one alert's events to."""

from __future__ import annotations

from collections.abc import Collection

from products.alerts.backend.logic.destinations import list_alert_destination_groups
from products.alerts_platform.backend.facade.contracts import AlertDestinationGroup


def list_delivery_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """An alert's HogFunction destinations. An insight alert's subscribers are `AlertDestination` rows on
    its platform copy, which the platform reads itself."""
    return list_alert_destination_groups(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
