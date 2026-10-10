"""Facade for native delivery: how other products plug in destinations and their own wording."""

from products.alerts_platform.backend.delivery import describers, destinations
from products.alerts_platform.backend.facade.contracts import DestinationResolver, SourceDescriber, SourceKind


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)


def register_source_describer(source: SourceKind, describer: SourceDescriber) -> None:
    describers.register(source, describer)
