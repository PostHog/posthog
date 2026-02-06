import dataclasses
from collections.abc import Callable
from typing import Any

from products.data_warehouse.backend.types import ExternalDataSourceType


@dataclasses.dataclass(frozen=True)
class SignalEmitterOutput:
    source_type: str
    source_id: str
    description: str
    weight: float
    extra: dict[str, Any]


# Type for signal emitter functions
SignalEmitter = Callable[[int, dict[str, Any]], SignalEmitterOutput]

# Registry mapping (source_type, schema_name) -> emitter function
_SIGNAL_EMITTERS: dict[tuple[str, str], SignalEmitter] = {}


def register_signal_emitter(source_type: ExternalDataSourceType, schema_name: str, emitter: SignalEmitter) -> None:
    """Register a signal emitter for a specific source type and schema."""
    _SIGNAL_EMITTERS[(source_type.value, schema_name)] = emitter


def get_signal_emitter(source_type: str, schema_name: str) -> SignalEmitter | None:
    """Get the signal emitter for a specific source type and schema."""
    return _SIGNAL_EMITTERS.get((source_type, schema_name))


def is_signal_emission_registered(source_type: str, schema_name: str) -> bool:
    """Check if signal emission is registered for a specific source type and schema."""
    return (source_type, schema_name) in _SIGNAL_EMITTERS


def _register_all_emitters() -> None:
    """Register all signal emitters. Called once on module load."""
    from posthog.temporal.data_imports.signals.zendesk import zendesk_ticket_emitter

    register_signal_emitter(ExternalDataSourceType.ZENDESK, "tickets", zendesk_ticket_emitter)


_register_all_emitters()
