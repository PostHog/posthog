from __future__ import annotations

from typing import Any, cast

from posthog.schema import RecordingOrder

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.session_recording_api import run_recordings_list_query
from posthog.session_recordings.utils import filter_from_params_to_query

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import SESSION_REPLAY_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.dashboards.backend.widgets.widget_filters import build_event_property_filters_from_widget_filters

ValidatedSessionReplayListWidgetConfig = dict[str, Any]

ORDER_BY_TO_RECORDING_ORDER: dict[str, RecordingOrder] = {
    "start_time": RecordingOrder.START_TIME,
    "activity_score": RecordingOrder.ACTIVITY_SCORE,
    "recording_duration": RecordingOrder.RECORDING_DURATION,
    "duration": RecordingOrder.DURATION,
    "click_count": RecordingOrder.CLICK_COUNT,
    "console_error_count": RecordingOrder.CONSOLE_ERROR_COUNT,
}


def _build_recordings_query(team: Team, config: ValidatedSessionReplayListWidgetConfig):
    date_range_raw = config.get("dateRange")
    date_from = "-7d"
    if date_range_raw is not None:
        date_from_value = date_range_raw.get("date_from")
        if isinstance(date_from_value, str):
            date_from = date_from_value

    params: dict[str, Any] = {
        "limit": config["limit"],
        "offset": 0,
        "date_from": date_from,
        "filter_test_accounts": resolve_filter_test_accounts(config, team),
        "order": ORDER_BY_TO_RECORDING_ORDER[config["orderBy"]],
        "order_direction": config["orderDirection"],
    }
    property_filters = build_event_property_filters_from_widget_filters(config.get("widgetFilters"))
    if property_filters:
        params["properties"] = property_filters

    return filter_from_params_to_query(params)


def _run_session_replay_list_query(
    team: Team,
    config: ValidatedSessionReplayListWidgetConfig,
    user: User | None,
) -> dict[str, Any]:
    query = _build_recordings_query(team, config)
    with tags_context(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk):
        return run_recordings_list_query(
            query=query,
            user=user,
            team=team,
            allow_event_property_expansion=False,
        )


def run_session_replay_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(SESSION_REPLAY_LIST_WIDGET_TYPE, config)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        page_config = cast(ValidatedSessionReplayListWidgetConfig, {**typed_config, "limit": page_limit})
        data = _run_session_replay_list_query(team, page_config, user)
        raw_results = data.get("results")
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=bool(data.get("has_next")),
        )

    return run_list_widget(
        limit=typed_config["limit"],
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        log_key="session_replay_widget_total_count_failed",
    )
