import dataclasses
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SignalSourceTableConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    emitter: SignalEmitter
    # Should match the source table's partition field for efficient ClickHouse queries
    partition_field: str
    # Columns to SELECT — only what the emitter and extra metadata need
    fields: tuple[str, ...]
    # Optional HogQL WHERE clause, e.g. "status NOT IN ('closed', 'solved')"
    where_clause: str | None = None
    # Max records to process per sync
    max_records: int = 1000
    # Set to True when the source stores datetime values as strings (e.g. GitHub JSON fields)
    partition_field_is_datetime_string: bool = False
    # How far back to look for new records
    first_sync_lookback_days: int = 7
    # LLM prompt to check if a record is actionable before emitting. If None, all records == actionable.
    actionability_prompt: str | None = None
    # LLM prompt to summarize descriptions that exceed the threshold. If None, no summarization is performed.
    summarization_prompt: str | None = None
    # How large the description can be before emitting
    description_summarization_threshold_chars: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_prompt_placeholders(self) -> "SignalSourceTableConfig":
        for field_name in ("actionability_prompt", "summarization_prompt"):
            value = getattr(self, field_name)
            if value is not None and "{description}" not in value:
                raise ValueError(f"{field_name} must contain {{description}} placeholder")
        return self

    @model_validator(mode="after")
    def _validate_summarization_pair(self) -> "SignalSourceTableConfig":
        has_prompt = self.summarization_prompt is not None
        has_threshold = self.description_summarization_threshold_chars is not None
        if has_prompt != has_threshold:
            raise ValueError(
                "summarization_prompt and description_summarization_threshold_chars must both be set or both be None"
            )
        return self


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
