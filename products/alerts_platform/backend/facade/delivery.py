"""Facade for native delivery: how the product that owns destinations plugs them in."""

from products.alerts_platform.backend.delivery import destinations
from products.alerts_platform.backend.facade.contracts import DestinationResolver


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)
