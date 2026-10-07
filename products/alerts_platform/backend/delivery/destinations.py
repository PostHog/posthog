"""Who a delivery sends to.

Destinations are HogFunction rows, and `products.alerts` owns them. The platform imports no other
product, so that product registers its lookup here when Django starts, and delivery asks this
module rather than the owner. This module goes away when destinations move into the platform.
"""

from collections.abc import Collection

from products.alerts_platform.backend.facade.contracts import AlertDestinationGroup, DestinationResolver

_resolver: DestinationResolver | None = None


def register(resolver: DestinationResolver) -> None:
    global _resolver
    # One owner. A second registrant would silently take every alert's destinations.
    if _resolver is not None and _resolver is not resolver:
        raise RuntimeError("A different destination resolver is already registered.")
    _resolver = resolver


def list_alert_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    # Raise rather than answer "no destinations". An empty answer would make a missing
    # registration look like an alert that nobody subscribed to, and nothing would report it.
    if _resolver is None:
        raise RuntimeError("No destination resolver is registered. products.alerts registers one in its ready().")
    return _resolver(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
