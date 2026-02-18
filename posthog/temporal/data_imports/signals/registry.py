import dataclasses
from collections.abc import Callable
from typing import Any

from products.data_warehouse.backend.types import ExternalDataSourceType

EMIT_SIGNALS_FEATURE_FLAG = "emit-data-import-signals"


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
class SignalSourceTableConfig:
    emitter: SignalEmitter
    # Column used to filter new records. Should match the source table's partition field for efficient ClickHouse queries.
    partition_field: str
    # Columns to SELECT — only what the emitter and extra metadata need
    fields: tuple[str, ...]
    # Optional HogQL WHERE clause to append to every query
    # e.g., "status NOT IN ('closed', 'solved')" for Zendesk
    where_clause: str | None = None
    # Max records to process per sync
    max_records: int = 1000
    # Lookback window in days for first ever sync
    first_sync_lookback_days: int = 7
    # Optional LLM prompt to check if a record is actionable before emitting.
    # If None, all records passing the emitter are considered actionable.
    actionability_prompt: str | None = None
    # Optional LLM prompt to summarize descriptions that exceed the threshold.
    # If None, no summarization is performed.
    summarization_prompt: str | None = None
    # Character limit above which descriptions are summarized (and truncated as last resort).
    # Only used when summarization_prompt is set.
    description_summarization_threshold: int | None = None


# Registry mapping (source_type, schema_name) -> config
_SIGNAL_TABLE_CONFIGS: dict[tuple[str, str], SignalSourceTableConfig] = {}


def register_signal_source_table(
    source_type: ExternalDataSourceType, schema_name: str, config: SignalSourceTableConfig
) -> None:
    _SIGNAL_TABLE_CONFIGS[(source_type.value, schema_name)] = config


def get_signal_config(source_type: str, schema_name: str) -> SignalSourceTableConfig | None:
    return _SIGNAL_TABLE_CONFIGS.get((source_type, schema_name))


def is_signal_emission_registered(source_type: str, schema_name: str) -> bool:
    return (source_type, schema_name) in _SIGNAL_TABLE_CONFIGS


def _register_all_emitters() -> None:
    from posthog.temporal.data_imports.signals.github_issues import GITHUB_ISSUES_CONFIG
    from posthog.temporal.data_imports.signals.zendesk_tickets import ZENDESK_TICKETS_CONFIG

    register_signal_source_table(ExternalDataSourceType.ZENDESK, "tickets", ZENDESK_TICKETS_CONFIG)
    register_signal_source_table(ExternalDataSourceType.GITHUB, "issues", GITHUB_ISSUES_CONFIG)


_register_all_emitters()
