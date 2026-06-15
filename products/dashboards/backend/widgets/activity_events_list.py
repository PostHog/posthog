from __future__ import annotations

import logging
from typing import Any, cast

from posthog.schema import EventsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import ACTIVITY_EVENTS_MAX_LIMIT
from products.dashboards.backend.widget_specs.configs import ACTIVITY_EVENTS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.widget_filters import build_event_property_filters_from_widget_filters

logger = logging.getLogger(__name__)

ValidatedActivityEventsListWidgetConfig = dict[str, Any]

DEFAULT_ACTIVITY_EVENTS_DATE_FROM = "-24h"

# Mirrors the /activity/explore DataTable's key columns; `person_display_name` keeps the
# query on ClickHouse (no per-row person lookup in Postgres, unlike the `person` column).
ACTIVITY_EVENTS_WIDGET_SELECT = [
    "uuid",
    "event",
    "person_display_name -- Person",
    "coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen",
    "properties.$lib -- Library",
    "timestamp",
]
ACTIVITY_EVENTS_WIDGET_RESULT_KEYS = ["uuid", "event", "person", "url", "lib", "timestamp"]


def _build_activity_events_query(
    team: Team,
    config: ValidatedActivityEventsListWidgetConfig,
    limit: int,
) -> EventsQuery:
    date_range_raw = config.get("dateRange")
    after = DEFAULT_ACTIVITY_EVENTS_DATE_FROM
    if date_range_raw is not None:
        date_from_value = date_range_raw.get("date_from")
        if isinstance(date_from_value, str):
            after = date_from_value

    property_filters = build_event_property_filters_from_widget_filters(config.get("widgetFilters"))

    return EventsQuery(
        kind="EventsQuery",
        select=ACTIVITY_EVENTS_WIDGET_SELECT,
        orderBy=["timestamp DESC"],
        after=after,
        filterTestAccounts=resolve_filter_test_accounts(config, team),
        properties=property_filters or None,
        limit=limit,
        offset=0,
    )


def _run_activity_events_query(
    team: Team,
    config: ValidatedActivityEventsListWidgetConfig,
    user: User | None,
    *,
    limit: int,
) -> dict[str, Any]:
    query = _build_activity_events_query(team, config, limit)
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        return EventsQueryRunner(team=team, query=query, user=user).calculate().model_dump(mode="json")


def _row_to_result(row: list[Any]) -> dict[str, Any]:
    return dict(zip(ACTIVITY_EVENTS_WIDGET_RESULT_KEYS, row))


def _count_matching_activity_events(
    team: Team,
    config: ValidatedActivityEventsListWidgetConfig,
    user: User | None,
    *,
    cap: int = ACTIVITY_EVENTS_MAX_LIMIT,
) -> tuple[int, bool]:
    data = _run_activity_events_query(team, config, user, limit=cap)
    raw_results_value = data.get("results")
    raw_results = raw_results_value if isinstance(raw_results_value, list) else []
    return len(raw_results), bool(data.get("hasMore"))


def run_activity_events_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(ACTIVITY_EVENTS_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]
    data = _run_activity_events_query(team, typed_config, user, limit=limit)
    raw_results_value = data.get("results")
    raw_results = cast(list[Any], raw_results_value) if isinstance(raw_results_value, list) else []
    results = [_row_to_result(row) for row in raw_results[:limit]]
    has_more = bool(data.get("hasMore"))
    shown = len(results)

    payload: dict[str, Any] = {
        "results": results,
        "hasMore": has_more,
        "limit": limit,
        "offset": 0,
    }

    if has_more:
        if include_total_count:
            try:
                total_count, total_count_capped = _count_matching_activity_events(team, typed_config, user)
                payload["totalCount"] = total_count
                payload["totalCountCapped"] = total_count_capped
            except Exception:
                logger.exception("activity_events_widget_total_count_failed")
                payload["totalCount"] = shown
                payload["totalCountCapped"] = True
    else:
        payload["totalCount"] = shown
        payload["totalCountCapped"] = False

    return payload
