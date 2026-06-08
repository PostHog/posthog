from __future__ import annotations

import logging
from typing import Any, cast

from posthog.schema import RecordingOrder

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.session_recording_api import run_recordings_list_query
from posthog.session_recordings.utils import filter_from_params_to_query

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widgets.config import (
    merge_base_widget_config_fields,
    resolve_filter_test_accounts,
    validate_widget_list_date_range_if_present,
    validate_widget_list_limit,
    validate_widget_list_order_by,
    validate_widget_list_order_direction,
)
from products.dashboards.backend.widgets.widget_config_types import (
    SessionReplayListWidgetConfig,
    SessionReplayListWidgetConfigInput,
)
from products.dashboards.backend.widgets.widget_filters import (
    build_event_property_filters_from_widget_filters,
    validate_widget_filters,
)

logger = logging.getLogger(__name__)

SESSION_REPLAY_ORDER_BY = frozenset(
    {
        "start_time",
        "activity_score",
        "recording_duration",
        "duration",
        "click_count",
        "console_error_count",
    }
)

ORDER_BY_TO_RECORDING_ORDER: dict[str, RecordingOrder] = {
    "start_time": RecordingOrder.START_TIME,
    "activity_score": RecordingOrder.ACTIVITY_SCORE,
    "recording_duration": RecordingOrder.RECORDING_DURATION,
    "duration": RecordingOrder.DURATION,
    "click_count": RecordingOrder.CLICK_COUNT,
    "console_error_count": RecordingOrder.CONSOLE_ERROR_COUNT,
}


def validate_session_replay_list_config(config: SessionReplayListWidgetConfigInput) -> SessionReplayListWidgetConfig:
    limit = validate_widget_list_limit(config)
    order_by = validate_widget_list_order_by(config, allowed=SESSION_REPLAY_ORDER_BY, default="start_time")
    order_direction = validate_widget_list_order_direction(config)
    validated_date_range = validate_widget_list_date_range_if_present(config)
    validated_widget_filters = validate_widget_filters(config)

    validated: SessionReplayListWidgetConfig = {
        "limit": limit,
        "orderBy": order_by,
        "orderDirection": order_direction,
    }
    if validated_date_range is not None:
        validated["dateRange"] = validated_date_range
    if validated_widget_filters is not None:
        validated["widgetFilters"] = validated_widget_filters
    base_fields = merge_base_widget_config_fields(config)
    if "filterTestAccounts" in base_fields:
        validated["filterTestAccounts"] = base_fields["filterTestAccounts"]
    return validated


def _build_recordings_query(team: Team, config: SessionReplayListWidgetConfig):
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
    config: SessionReplayListWidgetConfig,
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


def _count_matching_session_recordings(
    team: Team,
    config: SessionReplayListWidgetConfig,
    user: User | None,
    *,
    cap: int = MAX_WIDGET_RESULT_LIMIT,
) -> tuple[int, bool]:
    """Return how many recordings match the widget filters, and whether the count hit the cap."""
    count_config = cast(SessionReplayListWidgetConfig, {**config, "limit": cap})
    data = _run_session_replay_list_query(team, count_config, user)
    raw_results_value = data.get("results")
    raw_results = raw_results_value if isinstance(raw_results_value, list) else []
    return len(raw_results), bool(data.get("has_next"))


def run_session_replay_list_widget(
    team: Team,
    config: SessionReplayListWidgetConfigInput,
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_session_replay_list_config(config)
    limit = typed_config["limit"]
    data = _run_session_replay_list_query(team, typed_config, user)
    raw_results_value = data.get("results")
    raw_results = raw_results_value if isinstance(raw_results_value, list) else []
    results = raw_results[:limit]
    has_more = bool(data.get("has_next"))
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
                total_count, total_count_capped = _count_matching_session_recordings(team, typed_config, user)
                payload["totalCount"] = total_count
                payload["totalCountCapped"] = total_count_capped
            except Exception:
                logger.exception("session_replay_widget_total_count_failed")
                payload["totalCount"] = shown
                payload["totalCountCapped"] = True
    else:
        payload["totalCount"] = shown
        payload["totalCountCapped"] = False

    return payload
