from __future__ import annotations

import logging
from typing import Any

from posthog.schema import RecordingOrder, RecordingOrderDirection, RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.session_recordings.playlist_filters import convert_playlist_to_recordings_query
from posthog.session_recordings.session_recording_api import run_recordings_list_query
from posthog.session_recordings.utils import filter_from_params_to_query, recordings_query_has_event_filters

from products.dashboards.backend.constants import MAX_COLLECTION_SESSION_IDS, MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import SESSION_REPLAY_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
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


def _user_can_view_playlist(user: User | None, team: Team, playlist: SessionRecordingPlaylist) -> bool:
    # Mirror the object-level "viewer" access the playlist API enforces, so a widget can't surface a
    # playlist the requesting user isn't allowed to see. No-ops to True when access controls aren't
    # licensed/configured, so the common case (everyone can view) is unaffected.
    if user is None or user.is_anonymous:
        return False
    return UserAccessControl(user=user, team=team).check_access_level_for_object(playlist, "viewer")


def _build_saved_filter_recordings_query(
    team: Team,
    config: ValidatedSessionReplayListWidgetConfig,
    saved_filter_id: str,
    user: User | None,
) -> RecordingsQuery | None:
    # The saved filter (SessionRecordingPlaylist of type "filters") is the source of truth for
    # date range and property filters; the widget only layers its own sort and limit on top.
    playlist = SessionRecordingPlaylist.objects.filter(
        team=team, short_id=saved_filter_id, deleted=False, type="filters"
    ).first()
    # Treat a playlist the user can't view the same as a missing one — fall back without revealing it exists.
    if playlist is None or not _user_can_view_playlist(user, team, playlist):
        logger.warning("session_replay_widget_saved_filter_not_found", extra={"short_id": saved_filter_id})
        return None

    # Read path: convert legacy filters in-memory, never write back to the shared playlist row.
    query = convert_playlist_to_recordings_query(playlist, persist_legacy_conversion=False)
    query.limit = config["limit"]
    query.offset = 0
    query.order = ORDER_BY_TO_RECORDING_ORDER[config["orderBy"]]
    query.order_direction = RecordingOrderDirection(config["orderDirection"])
    return query


def _build_collection_session_ids(team: Team, collection_id: str, user: User | None) -> list[str] | None:
    # The pinned recordings of a collection (SessionRecordingPlaylist of type "collection"). Returns None when
    # the collection can't be reached (deleted, missing, or owned by another team) so the caller can ignore it.
    playlist = SessionRecordingPlaylist.objects.filter(
        team=team, short_id=collection_id, deleted=False, type="collection"
    ).first()
    # Treat a collection the user can't view the same as a missing one — fall back without revealing it exists.
    if playlist is None or not _user_can_view_playlist(user, team, playlist):
        logger.warning("session_replay_widget_collection_not_found", extra={"short_id": collection_id})
        return None

    # Legacy items can have a null recording FK (they used the deprecated session_id field instead); skip
    # them so no None leaks into session_ids and corrupts the ClickHouse IN clause. Cap the count so a huge
    # collection can't blow up the materialized list or the ClickHouse IN clause (the widget shows far fewer).
    return list(
        SessionRecordingPlaylistItem.objects.filter(playlist=playlist, recording__isnull=False)
        .exclude(deleted=True)
        .order_by("-created_at")
        .values_list("recording_id", flat=True)[:MAX_COLLECTION_SESSION_IDS]
    )


def _build_recordings_query(
    team: Team, config: ValidatedSessionReplayListWidgetConfig, user: User | None
) -> RecordingsQuery:
    collection_id = config.get("collectionId")
    collection_session_ids = _build_collection_session_ids(team, collection_id, user) if collection_id else None
    has_collection = collection_session_ids is not None

    # The query criteria come from the saved filter when one is set; otherwise from the widget's own controls.
    # A collection (if any) is then layered on as a session-id scope, so the date range / saved filter /
    # property filters all narrow within the collection.
    saved_filter_id = config.get("savedFilterId")
    query = _build_saved_filter_recordings_query(team, config, saved_filter_id, user) if saved_filter_id else None

    if query is None:
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

        query = filter_from_params_to_query(params)

    if has_collection:
        query.session_ids = collection_session_ids

    return query


def _build_matching_events_query(query: RecordingsQuery) -> dict[str, Any] | None:
    # The player highlights the events that matched the same filters the list was built from. We ship
    # the query the backend just resolved (saved-filter playlist included), so the client never has to
    # reconstruct it; it only adds the session id per row. The matching_events endpoint requires at
    # least one event/action/event-property filter, so omit the query when there's nothing to match.
    if not recordings_query_has_event_filters(query):
        return None

    payload = query.model_dump(mode="json", exclude_none=True)
    # The client sets session_ids per recording when opening the player.
    payload.pop("session_ids", None)
    return payload


def _run_recordings_query(team: Team, query: RecordingsQuery, user: User | None) -> dict[str, Any]:
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
    # Build once so a saved-filter playlist is fetched/converted only a single time; both the
    # visible page and the count page reuse it via model_copy with just the page limit.
    query = _build_recordings_query(team, typed_config, user)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        page_query = query.model_copy(update={"limit": page_limit, "offset": 0})
        data = _run_recordings_query(team, page_query, user)
        raw_results = data.get("results")
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=bool(data.get("has_next")),
        )

    result = run_list_widget(
        limit=typed_config["limit"],
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        log_key="session_replay_widget_total_count_failed",
    )

    matching_events_query = _build_matching_events_query(query)
    if matching_events_query is not None:
        result["matchingEventsQuery"] = matching_events_query

    return result
