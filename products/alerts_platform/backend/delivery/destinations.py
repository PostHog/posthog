"""Who a delivery sends to.

Destinations are HogFunction rows, and `products.alerts` owns them. The platform imports no other
product, so that product registers its lookup here when Django starts, and delivery asks this
module rather than the owner.
"""

from collections.abc import Collection
from typing import Final

from products.alerts_platform.backend.facade.contracts import AlertDestinationGroup, DestinationResolver


class DestinationRegistry:
    def __init__(self) -> None:
        self._resolver: DestinationResolver | None = None

    def register(self, resolver: DestinationResolver) -> None:
        self._resolver = resolver

    def groups(self, *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> list[AlertDestinationGroup]:
        # Raise rather than answer "no destinations". An empty answer would make a missing
        # registration look like an alert that nobody subscribed to, and nothing would report it.
        if self._resolver is None:
            raise RuntimeError("No destination resolver is registered. products.alerts registers one in its ready().")
        return self._resolver(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)


DESTINATIONS: Final = DestinationRegistry()


def list_alert_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    return DESTINATIONS.groups(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
