"""Facade for native delivery: how other products plug in destinations and their own wording."""

from products.alerts_platform.backend.delivery import addresses, describers, destinations
from products.alerts_platform.backend.facade.contracts import (
    DestinationResolver,
    DestinationType,
    SourceDescriber,
    SourceKind,
)


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)


def register_source_describer(source: SourceKind, describer: SourceDescriber) -> None:
    describers.register(source, describer)


def refused_address(destination_type: DestinationType, url: str) -> str | None:
    """Why native delivery would refuse to send to this URL, or None when it would send."""
    return addresses.refused_address(destination_type, url)
