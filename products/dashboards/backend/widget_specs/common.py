from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from posthog.schema import PropertyOperator

from products.dashboards.backend.constants import (
    ACTIVITY_EVENTS_MAX_LIMIT,
    LOGS_LIST_MAX_LIMIT,
    MAX_WIDGET_RESULT_LIMIT,
    WIDGET_DATE_FROM_VALUES_ORDERED,
)

WIDGET_DATE_FROM_VALUES = frozenset(WIDGET_DATE_FROM_VALUES_ORDERED)

WidgetDateFrom = Literal["-1M", "-30M", "-1h", "-3h", "-24h", "-7d", "-14d", "-30d", "-90d"]
WidgetOrderDirection = Literal["ASC", "DESC"]


class WidgetDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: WidgetDateFrom | None = None


class WidgetFilterEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filterId: str = Field(min_length=1)
    propertyName: str = Field(min_length=1)
    optionId: str = Field(min_length=1)
    operator: PropertyOperator
    value: str | list[str] | None = None

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str | list[str] | None) -> str | list[str] | None:
        if isinstance(value, list) and not all(isinstance(item, str) for item in value):
            raise ValueError("widgetFilters value list items must be strings.")
        return value


def validate_widget_filters_map(
    widget_filters: dict[str, WidgetFilterEntry] | None,
) -> dict[str, WidgetFilterEntry] | None:
    if widget_filters is None:
        return None
    for filter_id, entry in widget_filters.items():
        if not filter_id:
            raise ValueError("widgetFilters keys must be non-empty strings.")
        if entry.filterId != filter_id:
            raise ValueError(f"widgetFilters.{filter_id}.filterId must match the map key.")
    return widget_filters


class WidgetDateRangeConfigBase(BaseModel):
    """Shared base for widgets that accept a preset date range but not the full list-filter set."""

    model_config = ConfigDict(extra="forbid")

    dateRange: WidgetDateRange | None = None

    @field_validator("dateRange", mode="before")
    @classmethod
    def validate_date_range(cls, value: object) -> WidgetDateRange | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("dateRange must be an object.")
        date_from = value.get("date_from")
        if date_from is not None and (not isinstance(date_from, str) or date_from not in WIDGET_DATE_FROM_VALUES):
            allowed = ", ".join(sorted(WIDGET_DATE_FROM_VALUES))
            raise ValueError(f"dateRange.date_from must be one of: {allowed}.")
        return WidgetDateRange(date_from=date_from)


class WidgetListConfigBase(WidgetDateRangeConfigBase):
    filterTestAccounts: bool | None = None
    widgetFilters: dict[str, WidgetFilterEntry] | None = None

    @field_validator("filterTestAccounts", mode="before")
    @classmethod
    def validate_filter_test_accounts(cls, value: object) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("filterTestAccounts must be a boolean.")
        return value

    @field_validator("widgetFilters")
    @classmethod
    def validate_widget_filters(cls, value: dict[str, WidgetFilterEntry] | None) -> dict[str, WidgetFilterEntry] | None:
        return validate_widget_filters_map(value)


WidgetLimit = Annotated[int, Field(ge=1, le=MAX_WIDGET_RESULT_LIMIT)]
ActivityWidgetLimit = Annotated[int, Field(ge=1, le=ACTIVITY_EVENTS_MAX_LIMIT)]
LogsWidgetLimit = Annotated[int, Field(ge=1, le=LOGS_LIST_MAX_LIMIT)]
