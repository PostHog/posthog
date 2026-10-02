"""Facade for native delivery: how the product that owns destinations plugs them in."""

from products.alerts_platform.backend.delivery.destinations import DESTINATIONS
from products.alerts_platform.backend.facade.contracts import DestinationResolver

__all__ = ["DestinationResolver", "register_destination_resolver"]


def register_destination_resolver(resolver: DestinationResolver) -> None:
    DESTINATIONS.register(resolver)
