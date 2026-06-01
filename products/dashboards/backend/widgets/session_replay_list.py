from __future__ import annotations

from typing import Any, cast

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import RecordingOrder, RecordingOrderDirection, RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.session_recording_api import SessionRecordingSerializer, list_recordings_from_query

from products.dashboards.backend.constants import DEFAULT_SESSION_REPLAY_LIST_WIDGET_LIMIT, MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widgets.config import (
    merge_base_widget_config_fields,
    resolve_filter_test_accounts,
    validate_widget_date_range,
)

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


class _SessionRecordingListViewShim:
    """Skip list-view N+1 paths in SessionRecordingSerializer (external refs, summaries)."""

    action = "list"


ORDER_BY_TO_RECORDING_ORDER: dict[str, RecordingOrder] = {
    "start_time": RecordingOrder.START_TIME,
    "activity_score": RecordingOrder.ACTIVITY_SCORE,
    "recording_duration": RecordingOrder.RECORDING_DURATION,
    "duration": RecordingOrder.DURATION,
    "click_count": RecordingOrder.CLICK_COUNT,
    "console_error_count": RecordingOrder.CONSOLE_ERROR_COUNT,
}


def validate_session_replay_list_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise DRFValidationError({"config": "Config must be an object."})

    limit = config.get("limit", DEFAULT_SESSION_REPLAY_LIST_WIDGET_LIMIT)
    if not isinstance(limit, int) or limit < 1 or limit > MAX_WIDGET_RESULT_LIMIT:
        raise DRFValidationError({"config": f"limit must be an integer between 1 and {MAX_WIDGET_RESULT_LIMIT}."})

    order_by = config.get("orderBy", "start_time")
    if order_by not in SESSION_REPLAY_ORDER_BY:
        raise DRFValidationError({"config": f"orderBy must be one of: {', '.join(sorted(SESSION_REPLAY_ORDER_BY))}."})

    order_direction = config.get("orderDirection", "DESC")
    if order_direction not in {"ASC", "DESC"}:
        raise DRFValidationError({"config": "orderDirection must be ASC or DESC."})

    validated_date_range = validate_widget_date_range(config.get("dateRange")) if "dateRange" in config else None

    return {
        "limit": limit,
        "orderBy": order_by,
        "orderDirection": order_direction,
        **({"dateRange": validated_date_range} if validated_date_range is not None else {}),
        **merge_base_widget_config_fields(config),
    }


def _build_recordings_query(team: Team, config: dict[str, Any]) -> RecordingsQuery:
    limit = cast(int, config["limit"])
    order_by = cast(str, config.get("orderBy", "start_time"))
    order_direction = cast(str, config.get("orderDirection", "DESC"))
    date_range_raw = config.get("dateRange")
    date_from = "-7d"
    if isinstance(date_range_raw, dict) and isinstance(date_range_raw.get("date_from"), str):
        date_from = date_range_raw["date_from"]

    return RecordingsQuery(
        kind="RecordingsQuery",
        limit=limit,
        offset=0,
        date_from=date_from,
        date_to=None,
        filter_test_accounts=resolve_filter_test_accounts(config, team),
        order=ORDER_BY_TO_RECORDING_ORDER[order_by],
        order_direction=RecordingOrderDirection(order_direction),
    )


def run_session_replay_list_widget(team: Team, config: dict[str, Any], user: User | None = None) -> dict[str, Any]:
    query = _build_recordings_query(team, config)
    with tags_context(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk):
        recordings, has_more, _, _next_cursor = list_recordings_from_query(
            query=query,
            user=user,
            team=team,
            allow_event_property_expansion=False,
        )
    serializer = SessionRecordingSerializer(
        recordings,
        many=True,
        context={"view": _SessionRecordingListViewShim(), "get_team": lambda: team},
    )
    results = cast(list[dict[str, Any]], serializer.data)
    limit = cast(int, config["limit"])
    return {
        "results": results[:limit],
        "hasMore": has_more,
        "limit": limit,
        "offset": 0,
    }
