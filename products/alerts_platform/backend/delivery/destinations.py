"""Who a delivery sends to.

`products.alerts` owns every destination: the HogFunction rows a person configured, and the
subscriber email and in-app groups it adds for an insight alert. The platform imports no other
product, so that product registers its lookup here when Django starts, and delivery asks this
module rather than the owner. One lookup answers for every source. A source decides which groups
it can reach through the event ids it maps each kind onto, because the lookup answers per event
id. This module goes away when destinations move into the platform.
"""

from collections.abc import Collection
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationGroup,
    DestinationResolver,
    LiveHogFunctionLookup,
)

_resolver: DestinationResolver | None = None
_live_lookup: LiveHogFunctionLookup | None = None


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


def register_live_hog_function_lookup(lookup: LiveHogFunctionLookup) -> None:
    global _live_lookup
    if _live_lookup is not None and _live_lookup is not lookup:
        raise RuntimeError("A different HogFunction lookup is already registered.")
    _live_lookup = lookup


def live_hog_function_ids(*, team_id: int, hog_function_ids: Collection[UUID]) -> frozenset[UUID]:
    """The named HogFunctions that still exist. Without a registered lookup every one counts as
    existing, so a row that copies one is skipped rather than sent twice."""
    if not hog_function_ids:
        return frozenset()
    if _live_lookup is None:
        return frozenset(hog_function_ids)
    return _live_lookup(team_id=team_id, hog_function_ids=hog_function_ids)
