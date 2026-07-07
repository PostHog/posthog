from __future__ import annotations

from typing import Any

from posthog.schema import EventsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import ACTIVITY_EVENTS_MAX_LIMIT
from products.dashboards.backend.widget_specs.configs import ACTIVITY_EVENTS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.dashboards.backend.widgets.widget_filters import build_event_property_filters_from_widget_filters

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

    event_name = config.get("eventName")
    event = event_name if isinstance(event_name, str) and event_name else None

    return EventsQuery(
        kind="EventsQuery",
        select=ACTIVITY_EVENTS_WIDGET_SELECT,
        orderBy=["timestamp DESC"],
        after=after,
        event=event,
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


def run_activity_events_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(ACTIVITY_EVENTS_LIST_WIDGET_TYPE, config)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        data = _run_activity_events_query(team, typed_config, user, limit=page_limit)
        raw_results = data.get("results")
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=bool(data.get("hasMore")),
        )

    return run_list_widget(
        limit=typed_config["limit"],
        count_cap=ACTIVITY_EVENTS_MAX_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=_row_to_result,
        log_key="activity_events_widget_total_count_failed",
    )
