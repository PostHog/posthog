import re
from datetime import datetime, timedelta
from typing import Any

from django.utils.timezone import now

from dateutil.parser import isoparse

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.dashboards.backend.models.dashboard import Dashboard

MAX_SHARED_DASHBOARD_AUTO_REFRESH_RANGE = timedelta(days=30)
RELATIVE_DATE_EXPRESSION = re.compile(r"^-?(?:[0-9]+)?[hdwmqysHDWMQY](?:Start|End)?$")


def _query_date_range(query: dict[str, Any] | None) -> dict[str, Any]:
    if not query:
        return {}
    if isinstance(query.get("dateRange"), dict):
        return query["dateRange"]
    return _query_date_range(query.get("source")) if isinstance(query.get("source"), dict) else {}


def _has_date_range(filters: dict[str, Any] | None) -> bool:
    return bool(filters and (filters.get("date_from") is not None or filters.get("date_to") is not None))


def _is_valid_date_expression(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    if RELATIVE_DATE_EXPRESSION.fullmatch(value):
        return True
    try:
        isoparse(value)
    except (TypeError, ValueError, OverflowError):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            return False
    return True


def _date_range_exceeds_limit(filters: dict[str, Any], dashboard: Dashboard, current_time: datetime) -> bool:
    if filters.get("date_from") == "all":
        return True
    if not _is_valid_date_expression(filters.get("date_from")) or not _is_valid_date_expression(filters.get("date_to")):
        return True

    try:
        query_date_range = QueryDateRange(
            date_range=DateRange(
                date_from=filters.get("date_from") or "-7d",
                date_to=filters.get("date_to"),
                explicitDate=filters.get("explicitDate", False),
            ),
            team=dashboard.team,
            interval=IntervalType.DAY,
            now=current_time,
            exact_timerange=True,
        )
        return query_date_range.date_to() - query_date_range.date_from() > MAX_SHARED_DASHBOARD_AUTO_REFRESH_RANGE
    except (TypeError, ValueError, OverflowError):
        return True


def dashboard_allows_auto_refresh(dashboard: Dashboard, current_time: datetime | None = None) -> bool:
    current_time = current_time or now()
    dashboard_filters = dashboard.filters or {}

    if _has_date_range(dashboard_filters) and _date_range_exceeds_limit(dashboard_filters, dashboard, current_time):
        return False

    for tile in dashboard.tiles.select_related("insight").filter(insight__deleted=False):
        if tile.insight is None:
            continue

        tile_filters = tile.filters_overrides or {}
        if _has_date_range(tile_filters):
            effective_date_range = tile_filters
        elif _has_date_range(dashboard_filters):
            effective_date_range = dashboard_filters
        else:
            effective_date_range = _query_date_range(tile.insight.query) or tile.insight.filters or {}

        if _date_range_exceeds_limit(effective_date_range, dashboard, current_time):
            return False

    return True
