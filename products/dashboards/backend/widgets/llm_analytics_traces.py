from __future__ import annotations

from typing import Any

from posthog.schema import DateRange, TracesQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import LLM_ANALYTICS_TRACES_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.dashboards.backend.widgets.widget_filters import build_event_property_filters_from_widget_filters

ValidatedLlmAnalyticsTracesWidgetConfig = dict[str, Any]

DEFAULT_LLM_ANALYTICS_TRACES_DATE_FROM = "-7d"

# Compact subset of LLMTrace shown in the tile. The full trace carries heavy `events`,
# `inputState`, and `outputState` payloads — those are dropped so each tile refresh stays small.
# `id` is handled separately (required) so the optional fields can be omitted when absent.
LLM_ANALYTICS_TRACE_FIELDS = [
    "traceName",
    "createdAt",
    "totalLatency",
    "totalCost",
    "inputTokens",
    "outputTokens",
    "errorCount",
    "person",
    "distinctId",
]


def _build_traces_query(
    team: Team,
    config: ValidatedLlmAnalyticsTracesWidgetConfig,
    limit: int,
) -> TracesQuery:
    date_range_raw = config.get("dateRange")
    date_from = DEFAULT_LLM_ANALYTICS_TRACES_DATE_FROM
    if isinstance(date_range_raw, dict):
        date_from_value = date_range_raw.get("date_from")
        if isinstance(date_from_value, str):
            date_from = date_from_value

    property_filters = build_event_property_filters_from_widget_filters(config.get("widgetFilters"))

    return TracesQuery(
        kind="TracesQuery",
        dateRange=DateRange(date_from=date_from),
        filterTestAccounts=resolve_filter_test_accounts(config, team),
        filterSupportTraces=config.get("filterSupportTraces"),
        properties=property_filters or None,
        limit=limit,
        offset=0,
    )


def _run_traces_query(
    team: Team,
    config: ValidatedLlmAnalyticsTracesWidgetConfig,
    user: User | None,
    *,
    limit: int,
) -> dict[str, Any]:
    query = _build_traces_query(team, config, limit)
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        return TracesQueryRunner(team=team, query=query, user=user).calculate().model_dump(mode="json")


def _pick_trace_fields(trace: dict[str, Any]) -> dict[str, Any]:
    # `id` is required — fail fast if the runner omits it rather than emit a row that would
    # silently break the frontend trace link and React row key.
    return {"id": trace["id"], **{field: trace[field] for field in LLM_ANALYTICS_TRACE_FIELDS if field in trace}}


def run_llm_analytics_traces_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(LLM_ANALYTICS_TRACES_WIDGET_TYPE, config)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        data = _run_traces_query(team, typed_config, user, limit=page_limit)
        raw_results = data.get("results")
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=bool(data.get("hasMore")),
        )

    return run_list_widget(
        limit=typed_config["limit"],
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=_pick_trace_fields,
        log_key="llm_analytics_traces_widget_total_count_failed",
    )
