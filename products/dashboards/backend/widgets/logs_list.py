from __future__ import annotations

from typing import Any, cast

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import LOGS_LIST_MAX_LIMIT
from products.dashboards.backend.widget_specs.configs import LOGS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.logs.backend.facade.queries import LogsQueryRunner, build_logs_query_for_saved_view

ValidatedLogsListWidgetConfig = dict[str, Any]

DEFAULT_LOGS_WIDGET_DATE_FROM = "-1h"

# Compact subset of the log row the widget renders; the full attribute maps are dropped via
# `excludeAttributes` to keep the tile payload small.
# Required fields are read directly so a missing value fails fast; optional fields stay lenient.
LOGS_WIDGET_REQUIRED_FIELDS = ("uuid", "timestamp", "body")
LOGS_WIDGET_OPTIONAL_FIELDS = ("severity_text", "level", "trace_id")


def _resolve_date_from(config: ValidatedLogsListWidgetConfig) -> str:
    date_range_raw = config.get("dateRange")
    if date_range_raw is not None:
        date_from_value = date_range_raw.get("date_from")
        if isinstance(date_from_value, str):
            return date_from_value
    return DEFAULT_LOGS_WIDGET_DATE_FROM


def _build_logs_query(team: Team, config: ValidatedLogsListWidgetConfig, limit: int) -> LogsQuery:
    saved_view_id = config.get("savedViewId")
    if saved_view_id:
        query = build_logs_query_for_saved_view(
            team,
            saved_view_id,
            order_by=config["orderBy"],
            limit=limit,
            offset=0,
            exclude_attributes=True,
        )
        if query is not None:
            return query
        # Saved view was deleted or never existed — fall back to the widget's own config.

    return LogsQuery(
        kind="LogsQuery",
        dateRange=DateRange(date_from=_resolve_date_from(config), date_to=None),
        severityLevels=config.get("severityLevels") or [],
        serviceNames=config.get("serviceNames") or [],
        filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
        orderBy=config["orderBy"],
        limit=limit,
        offset=0,
        excludeAttributes=True,
    )


def _run_logs_query(team: Team, query: LogsQuery) -> dict[str, Any]:
    with tags_context(product=Product.LOGS, feature=Feature.QUERY, team_id=team.pk):
        return LogsQueryRunner(team=team, query=query).calculate().model_dump(mode="json")


def _transform_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **{field: row[field] for field in LOGS_WIDGET_REQUIRED_FIELDS},
        **{field: row.get(field) for field in LOGS_WIDGET_OPTIONAL_FIELDS},
    }


def run_logs_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(LOGS_LIST_WIDGET_TYPE, config)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        data = _run_logs_query(team, _build_logs_query(team, typed_config, page_limit))
        raw_results = data.get("results")
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=bool(data.get("hasMore")),
        )

    return run_list_widget(
        limit=typed_config["limit"],
        count_cap=LOGS_LIST_MAX_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=lambda row: _transform_row(cast(dict[str, Any], row)),
        log_key="logs_widget_total_count_failed",
    )
