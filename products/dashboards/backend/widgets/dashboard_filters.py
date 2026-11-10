"""Dashboard filters for widget tiles.

Widget tiles run through `run_widgets`, not the insight query path, so dashboard filters reach them
here. A widget type opts in per filter kind with `WidgetSpec.dashboard_filters`, and its runner
receives a `WidgetDashboardFilters` that only carries the kinds it declared.

Precedence matches insight tiles: a dashboard date range or test-account setting replaces the
widget's own, and dashboard property filters are ANDed onto the widget's own property filters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from posthog.hogql_queries.apply_dashboard_filters import (
    merge_filters_by_priority,
    normalize_dashboard_filters_properties,
)
from posthog.hogql_queries.utils.dashboard_filter_conflicts import filters_contradict
from posthog.hogql_queries.utils.query_date_range import CALENDAR_DAY_RE
from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.dashboards.backend.widget_specs.common import WidgetDashboardFilterKind
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts

# Dashboard `date_from` value that means no lower bound.
ALL_TIME_DATE_FROM = "all"


@dataclass(frozen=True)
class WidgetDashboardFilters:
    date_from: str | None = None
    date_to: str | None = None
    filter_test_accounts: bool | None = None
    properties: tuple[dict[str, Any], ...] = ()

    @property
    def has_date_range(self) -> bool:
        return self.date_from is not None or self.date_to is not None

    def resolve_date_range(
        self, config: Mapping[str, Any], default_date_from: str | None
    ) -> tuple[str | None, str | None]:
        """The date range a widget queries: the dashboard's when it sets one, else the widget's preset."""
        if self.has_date_range:
            return self.date_from or default_date_from, self.date_to
        date_range = config.get("dateRange")
        if isinstance(date_range, Mapping) and isinstance(date_range.get("date_from"), str):
            return date_range["date_from"], None
        return default_date_from, None

    def resolve_filter_test_accounts(self, config: Mapping[str, object], team: Team) -> bool:
        if self.filter_test_accounts is not None:
            return self.filter_test_accounts
        return resolve_filter_test_accounts(config, team)

    def with_properties(self, property_filters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        # Same rule as insight tiles: a widget filter that a dashboard filter contradicts is dropped, so
        # `$browser = Chrome` on the widget and `$browser = Firefox` on the dashboard shows Firefox, not nothing.
        own_filters = [
            own
            for own in property_filters or []
            if not any(filters_contradict(own, dashboard_filter) for dashboard_filter in self.properties)
        ]
        return [*own_filters, *self.properties]


NO_DASHBOARD_FILTERS = WidgetDashboardFilters()


def parse_widget_datetime(value: str | None, team: Team, *, end_of_day: bool = False) -> datetime | None:
    """Parse a widget date bound. "all" and None give an open bound.

    Set `end_of_day` for an upper bound, so that a calendar day such as `2026-09-01` includes that whole
    day, as it does on insight tiles.
    """
    if value is None or value == ALL_TIME_DATE_FROM:
        return None
    parsed = relative_date_parse(value, team.timezone_info)
    if end_of_day and CALENDAR_DAY_RE.fullmatch(value.strip()):
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def _clamp_date_from(date_from: str | None, max_date_from: str | None, team: Team) -> str | None:
    if date_from is None or max_date_from is None:
        return date_from
    if date_from == ALL_TIME_DATE_FROM:
        return max_date_from
    earliest = relative_date_parse(max_date_from, team.timezone_info)
    return max_date_from if relative_date_parse(date_from, team.timezone_info) < earliest else date_from


def build_widget_dashboard_filters(
    dashboard_filters: dict[str, Any] | None,
    tile_filters_overrides: dict[str, Any] | None,
    supported: frozenset[WidgetDashboardFilterKind],
    *,
    team: Team,
    max_date_from: str | None,
) -> WidgetDashboardFilters:
    """Merge the dashboard and tile filter layers like insight tiles do, keeping only the supported kinds.

    A date range that starts before `max_date_from`, or covers all time, starts at `max_date_from`, so a
    dashboard filter cannot make a widget query more than the widget allows on its own. None means no limit.
    """
    effective = normalize_dashboard_filters_properties(
        merge_filters_by_priority(dashboard_filters or {}, tile_filters_overrides or {})
    )

    date_from = effective.get("date_from") if "date_range" in supported else None
    date_to = effective.get("date_to") if "date_range" in supported else None
    filter_test_accounts = effective.get("filterTestAccounts") if "filter_test_accounts" in supported else None
    properties = effective.get("properties") if "properties" in supported else None

    return WidgetDashboardFilters(
        date_from=_clamp_date_from(date_from if isinstance(date_from, str) else None, max_date_from, team),
        date_to=date_to if isinstance(date_to, str) else None,
        filter_test_accounts=filter_test_accounts if isinstance(filter_test_accounts, bool) else None,
        properties=tuple(prop for prop in properties or [] if isinstance(prop, dict)),
    )
