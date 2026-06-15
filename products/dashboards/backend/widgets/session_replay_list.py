from __future__ import annotations

import logging
from typing import Any

from posthog.schema import RecordingOrder, RecordingOrderDirection, RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.playlist_filters import convert_playlist_to_recordings_query
from posthog.session_recordings.session_recording_api import run_recordings_list_query
from posthog.session_recordings.utils import filter_from_params_to_query

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import SESSION_REPLAY_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.widget_filters import build_event_property_filters_from_widget_filters

logger = logging.getLogger(__name__)

ValidatedSessionReplayListWidgetConfig = dict[str, Any]

ORDER_BY_TO_RECORDING_ORDER: dict[str, RecordingOrder] = {
    "start_time": RecordingOrder.START_TIME,
    "activity_score": RecordingOrder.ACTIVITY_SCORE,
    "recording_duration": RecordingOrder.RECORDING_DURATION,
    "duration": RecordingOrder.DURATION,
    "click_count": RecordingOrder.CLICK_COUNT,
    "console_error_count": RecordingOrder.CONSOLE_ERROR_COUNT,
}


def _build_saved_filter_recordings_query(
    team: Team,
    config: ValidatedSessionReplayListWidgetConfig,
    saved_filter_id: str,
) -> RecordingsQuery | None:
    # The saved filter (SessionRecordingPlaylist of type "filters") is the source of truth for
    # date range and property filters; the widget only layers its own sort and limit on top.
    playlist = SessionRecordingPlaylist.objects.filter(team=team, short_id=saved_filter_id, deleted=False).first()
    if playlist is None:
        logger.warning("session_replay_widget_saved_filter_not_found", extra={"short_id": saved_filter_id})
        return None

    # Read path: convert legacy filters in-memory, never write back to the shared playlist row.
    query = convert_playlist_to_recordings_query(playlist, persist_legacy_conversion=False)
    query.limit = config["limit"]
    query.offset = 0
    query.order = ORDER_BY_TO_RECORDING_ORDER[config["orderBy"]]
    query.order_direction = RecordingOrderDirection(config["orderDirection"])
    return query


def _build_recordings_query(team: Team, config: ValidatedSessionReplayListWidgetConfig) -> RecordingsQuery:
    saved_filter_id = config.get("savedFilterId")
    if saved_filter_id:
        saved_filter_query = _build_saved_filter_recordings_query(team, config, saved_filter_id)
        if saved_filter_query is not None:
            return saved_filter_query

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


def _run_recordings_query(team: Team, query: RecordingsQuery, user: User | None) -> dict[str, Any]:
    with tags_context(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk):
        return run_recordings_list_query(
            query=query,
            user=user,
            team=team,
            allow_event_property_expansion=False,
        )


def _count_matching_session_recordings(
    team: Team,
    query: RecordingsQuery,
    user: User | None,
    *,
    cap: int = MAX_WIDGET_RESULT_LIMIT,
) -> tuple[int, bool]:
    # Reuse the already-built query (a saved-filter playlist is only fetched/converted once) and
    # only raise the limit to the count cap.
    count_query = query.model_copy(update={"limit": cap})
    data = _run_recordings_query(team, count_query, user)
    raw_results_value = data.get("results")
    raw_results = raw_results_value if isinstance(raw_results_value, list) else []
    return len(raw_results), bool(data.get("has_next"))


def run_session_replay_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(SESSION_REPLAY_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]
    query = _build_recordings_query(team, typed_config)
    data = _run_recordings_query(team, query, user)
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
                total_count, total_count_capped = _count_matching_session_recordings(team, query, user)
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
