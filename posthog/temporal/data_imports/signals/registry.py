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


# Type for signal emitter functions (None if the source has not enough meaningful data)
SignalEmitter = Callable[[int, dict[str, Any]], SignalEmitterOutput | None]


@dataclasses.dataclass(frozen=True)
class SignalSourceConfig:
    emitter: SignalEmitter
    # Optional HogQL WHERE clause to append to every query
    # e.g., "status NOT IN ('closed', 'solved')" for Zendesk
    where_clause: str | None = None
    # Max records on first ever sync
    first_sync_limit: int = 100
    # Lookback window in days for first ever sync
    first_sync_lookback_days: int = 7
    # Optional LLM prompt to check if a record is actionable before emitting.
    # Must contain {description} placeholder. LLM should respond with ACTIONABLE or NOT_ACTIONABLE.
    # If None, all records passing the emitter are considered actionable.
    actionability_prompt: str | None = None


# Registry mapping (source_type, schema_name) -> config
_SIGNAL_CONFIGS: dict[tuple[str, str], SignalSourceConfig] = {}


def register_signal_source(source_type: ExternalDataSourceType, schema_name: str, config: SignalSourceConfig) -> None:
    _SIGNAL_CONFIGS[(source_type.value, schema_name)] = config


def get_signal_config(source_type: str, schema_name: str) -> SignalSourceConfig | None:
    return _SIGNAL_CONFIGS.get((source_type, schema_name))


def is_signal_emission_registered(source_type: str, schema_name: str) -> bool:
    return (source_type, schema_name) in _SIGNAL_CONFIGS


def _register_all_emitters() -> None:
    from posthog.temporal.data_imports.signals.zendesk import ZENDESK_TICKETS_CONFIG

    register_signal_source(ExternalDataSourceType.ZENDESK, "tickets", ZENDESK_TICKETS_CONFIG)


_register_all_emitters()
