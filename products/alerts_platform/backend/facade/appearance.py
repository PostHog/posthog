"""Facade for appearance alerts: how a source plugs in what is new, and what its alerts filter on.

A source registers an occurrence store that reads its own tables, or a feed that the platform's
registry records. The platform evaluates every appearance alert itself.
"""

from collections.abc import Callable
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model

from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_GROUPING,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    OccurrenceFeed,
    OccurrenceStore,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.logic import occurrences

# An appearance check reads a window that the store has finished, so a shorter cadence only adds checks.
APPEARANCE_CHECK_INTERVAL_MINUTES: Final = 1
MAX_FILTERS: Final = 20
MAX_FILTER_VALUES: Final = 50

FilterOperator = Literal["exact", "is_not", "icontains", "not_icontains"]


class AppearanceLabelFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="The label the filter reads, such as `service_name`.")
    operator: FilterOperator = Field(
        default="exact",
        description="exact and is_not compare the whole value with each of `values`. icontains and not_icontains "
        "look for each of `values` inside it, ignoring case.",
    )
    values: list[str] = Field(min_length=1, max_length=MAX_FILTER_VALUES, description="The values to compare with.")

    def matches(self, labels: dict[str, str]) -> bool:
        value = labels.get(self.key, "")
        if self.operator == "exact":
            return value in self.values
        if self.operator == "is_not":
            return value not in self.values
        found = any(candidate.lower() in value.lower() for candidate in self.values)
        return found if self.operator == "icontains" else not found


def _filters_field() -> Any:
    return Field(
        default_factory=list,
        max_length=MAX_FILTERS,
        description="An identity is announced only when it matches every filter. No filters announces every identity.",
    )


class AppearanceAlertConfig(BaseModel):
    """What every appearance alert's `source_config` holds. A source narrows the label keys it accepts."""

    model_config = ConfigDict(extra="forbid")

    filters: list[AppearanceLabelFilter] = _filters_field()

    def matches(self, labels: dict[str, str]) -> bool:
        return all(label_filter.matches(labels) for label_filter in self.filters)


def appearance_source_config(
    *,
    name: str,
    filter_keys: tuple[str, ...],
    rollout_flag: str,
    alert_url: Callable[[int, UUID], str] | None = None,
    create_warning: Callable[[int], str | None] | None = None,
) -> SourceConfigSpec:
    """The `source_config` schema and native lifecycle for a source's appearance alerts.

    `filter_keys` are the labels the source puts on its occurrences, which are the only keys a filter may name.
    """
    key_type: Any = Literal[filter_keys]
    label_filter = create_model(
        f"{name}Filter",
        __base__=AppearanceLabelFilter,
        key=(key_type, Field(description="The label the filter reads.")),
    )
    model = create_model(
        f"{name}Config",
        __base__=AppearanceAlertConfig,
        filters=(
            list[label_filter],
            _filters_field(),
        ),
    )
    return SourceConfigSpec(
        model=model,
        validate=_validate_edit,
        native=NativeAlertLifecycle(check_interval_minutes=APPEARANCE_CHECK_INTERVAL_MINUTES),
        alert_url=alert_url,
        rollout_flag=rollout_flag,
        create_warning=create_warning,
    )


def _validate_edit(edit: PlatformAlertConfigurationEdit) -> None:
    if not edit.grouping.splits_like(APPEARANCE_GROUPING):
        raise InvalidPlatformAlertEdit(
            "grouping",
            f"An appearance alert groups by the `{APPEARANCE_GROUPING.keys[0]}` label, so each identity has its own instance.",
        )
    if edit.evaluation_periods != 1 or edit.datapoints_to_alarm != 1:
        raise InvalidPlatformAlertEdit("evaluation_periods", "An appearance alert announces each identity once.")


def register_occurrence_store(source: SourceKind, store: OccurrenceStore) -> None:
    """A source with detection of its own answers what is new from its own tables."""
    occurrences.register_store(source, store)


def register_occurrence_feed(source: SourceKind, feed: OccurrenceFeed) -> None:
    """A source without detection reports what it saw, and the platform's registry decides what is new."""
    occurrences.register_feed(source, feed)
