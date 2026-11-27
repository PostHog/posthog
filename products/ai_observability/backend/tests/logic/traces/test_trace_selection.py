from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from parameterized import parameterized
from pydantic import TypeAdapter

from posthog.schema import AnyPropertyFilterDiscriminated

from posthog.models import Team

from products.ai_observability.backend.logic.traces.trace_selection import (
    ALL_TIME_LOOKBACK,
    CAPTURE_BUFFER,
    MAX_PROPERTY_FILTERS,
    InvalidTraceCursorError,
    InvalidTraceSelectionError,
    InvalidTraceWindowError,
    TraceGroupScope,
    TracePosition,
    TraceSelection,
    TraceWindow,
    decode_cursor,
    encode_cursor,
    filters_test_accounts,
    resolve_window,
)

T0 = datetime(2026, 9, 1, 10, 0, 0, 123456, tzinfo=UTC)
KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
WINDOW = TraceWindow(start=T0, end=T0 + timedelta(hours=1))
_PROPERTY_FILTER = TypeAdapter(AnyPropertyFilterDiscriminated)


def kolkata_team() -> Team:
    # Away from UTC, a bound read as a wall-clock time in the wrong zone lands hours off.
    return Team(timezone="Asia/Kolkata")


def selection_with(*filters: dict[str, Any]) -> TraceSelection:
    return TraceSelection(window=WINDOW, properties=tuple(_PROPERTY_FILTER.validate_python(item) for item in filters))


@parameterized.expand(
    [
        ("plain", "trace-1"),
        ("comma and quote", "a,b'\"c"),
        ("slash", "eval/trace"),
        ("long", "x" * 128),
        ("unicode", "trazo-ñ"),
    ]
)
def test_cursor_round_trips_any_trace_id(_name: str, trace_id: str) -> None:
    position = TracePosition(trace_id=trace_id, first_timestamp=T0)
    assert decode_cursor(encode_cursor(position)) == position


@parameterized.expand(
    [
        ("not base64", "%%%"),
        ("not json", "bm90IGpzb24"),
        ("wrong shape", "WzFd"),
        ("empty", ""),
        ("string time", "WyIxIiwidCJd"),
        ("boolean time", "W3RydWUsInQiXQ"),
        ("time past the last datetime", "Wzk5OTk5OTk5OTk5OTk5OTk5OTk5LCJ0Il0"),
    ]
)
def test_decode_cursor_rejects_garbage(_name: str, cursor: str) -> None:
    with pytest.raises(InvalidTraceCursorError):
        decode_cursor(cursor)


def test_sort_key_is_the_millisecond_of_the_first_event() -> None:
    position = TracePosition(trace_id="t", first_timestamp=T0.astimezone(KOLKATA))
    assert position.sort_key == int(T0.timestamp()) * 1000 + 123


@parameterized.expand(
    [
        ("utc", TraceWindow(start=T0, end=T0 + timedelta(hours=1))),
        (
            "second pass through a repeated dst hour",
            TraceWindow(
                start=datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NEW_YORK),
                end=datetime(2026, 11, 1, 1, 50, fold=1, tzinfo=NEW_YORK),
            ),
        ),
    ]
)
def test_read_bounds_widen_by_the_capture_buffer(_name: str, window: TraceWindow) -> None:
    bounds = window.read_bounds()

    assert window.start.astimezone(UTC) - bounds.start.astimezone(UTC) == CAPTURE_BUFFER
    assert bounds.end.astimezone(UTC) - window.end.astimezone(UTC) == CAPTURE_BUFFER


def test_window_defaults_to_the_last_seven_days() -> None:
    window = resolve_window(kolkata_team(), None, None, now=T0)
    assert abs((window.end - window.start) - timedelta(days=7)) < timedelta(minutes=1)
    assert abs(window.end - T0) < timedelta(minutes=1)


def test_a_calendar_day_date_to_includes_that_whole_day_in_the_project_timezone() -> None:
    window = resolve_window(kolkata_team(), "2026-08-30", "2026-08-31", now=T0)
    assert window == TraceWindow(
        start=datetime(2026, 8, 30, tzinfo=KOLKATA),
        end=datetime(2026, 8, 31, 23, 59, 59, 999999, tzinfo=KOLKATA),
    )


def test_a_date_without_zero_padding_reads_as_that_day() -> None:
    window = resolve_window(kolkata_team(), "2026-8-30", "2026-8-31", now=T0)
    assert window.start == datetime(2026, 8, 30, tzinfo=KOLKATA)


def test_all_reaches_back_by_the_all_time_lookback() -> None:
    window = resolve_window(kolkata_team(), "all", None, now=T0)
    assert window.end - window.start == ALL_TIME_LOOKBACK


def test_an_explicit_bound_reads_past_the_all_time_lookback() -> None:
    window = resolve_window(kolkata_team(), "-5y", None, now=T0)
    assert window.end - window.start > ALL_TIME_LOOKBACK


@parameterized.expand(
    [
        ("days", "-7d"),
        ("hours", "-2h"),
        ("minutes", "-30M"),
        ("seconds", "-45s"),
        ("quarters", "-1q"),
        ("start of day", "dStart"),
        ("start of week", "wStart"),
        ("start of year", "yStart"),
    ]
)
def test_accepts_a_relative_bound_the_parser_moves(_name: str, date_from: str) -> None:
    window = resolve_window(kolkata_team(), date_from, None, now=T0)
    assert window.start < T0


@parameterized.expand(
    [
        ("from after to", "2026-09-02", "2026-09-01"),
        ("unparsable from", "nonsense", None),
        ("unparsable to", None, "nonsense"),
        ("uppercase day", "-7D", None),
        ("uppercase hour", "-7H", None),
        ("uppercase week", "-1W", None),
        ("uppercase quarter", "-1Q", None),
        ("uppercase year", "-1Y", None),
        ("kind without a number or position", "d", None),
        ("trailing text", "-7days", None),
        ("start before the first datetime", "0001-01-01", None),
        ("end after the last datetime", None, "9999-12-31"),
        ("relative bound before the first datetime", "-99999y", None),
    ]
)
def test_rejects_impossible_ranges(_name: str, date_from: str | None, date_to: str | None) -> None:
    with pytest.raises(InvalidTraceWindowError):
        resolve_window(kolkata_team(), date_from, date_to, now=T0)


@parameterized.expand(
    [
        ("first pass to second pass", "2026-11-01T01:50:00-04:00", "2026-11-01T01:10:00-05:00", True),
        ("second pass to first pass", "2026-11-01T01:10:00-05:00", "2026-11-01T01:50:00-04:00", False),
    ]
)
def test_bounds_in_the_repeated_dst_hour_are_ordered_by_instant(
    _name: str, date_from: str, date_to: str, is_valid: bool
) -> None:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    if is_valid:
        window = resolve_window(Team(timezone="America/New_York"), date_from, date_to, now=now)
        assert window.end.astimezone(UTC) - window.start.astimezone(UTC) == timedelta(minutes=20)
    else:
        with pytest.raises(InvalidTraceWindowError):
            resolve_window(Team(timezone="America/New_York"), date_from, date_to, now=now)


@parameterized.expand(
    [
        ("unset follows a project default of on", None, True, True),
        ("unset follows a project default of off", None, False, False),
        ("off overrides a project default of on", False, True, False),
    ]
)
def test_test_account_filtering_follows_the_project_unless_set(
    _name: str, filter_test_accounts: bool | None, project_default: bool, expected: bool
) -> None:
    team = Team(test_account_filters_default_checked=project_default)
    selection = TraceSelection(window=WINDOW, filter_test_accounts=filter_test_accounts)
    assert filters_test_accounts(team, selection) is expected


def test_a_selection_accepts_every_filter_type_traces_support_up_to_the_limit() -> None:
    supported: list[dict[str, Any]] = [
        {"type": "event", "key": "tier", "value": "gold", "operator": "exact"},
        {"type": "event", "key": "$ai_model", "value": "gpt-4o", "operator": "exact"},
        {"type": "event_metadata", "key": "distinct_id", "value": "user-1", "operator": "exact"},
        {"type": "person", "key": "email", "value": "user@example.com", "operator": "exact"},
        {"type": "session", "key": "$session_duration", "value": 1, "operator": "gt"},
        {"type": "group", "key": "plan", "value": "pro", "operator": "exact", "group_type_index": 0},
        {"type": "cohort", "key": "id", "value": 1},
        {"type": "element", "key": "tag_name", "value": "a", "operator": "exact"},
        {"type": "hogql", "key": "1 = 1"},
        {"type": "data_warehouse", "key": "plan", "value": "pro", "operator": "exact"},
        {"type": "data_warehouse_person_property", "key": "billing.plan", "value": "pro", "operator": "exact"},
    ]
    filler = [supported[0]] * (MAX_PROPERTY_FILTERS - len(supported))

    assert len(selection_with(*supported, *filler).properties) == MAX_PROPERTY_FILTERS


@parameterized.expand(
    [
        ("a type traces do not support", [{"type": "recording", "key": "duration", "value": 10, "operator": "gt"}]),
        (
            "more filters than the limit",
            [{"type": "event", "key": "tier", "value": "gold", "operator": "exact"}] * (MAX_PROPERTY_FILTERS + 1),
        ),
        (
            "a warehouse person filter without a table",
            [{"type": "data_warehouse_person_property", "key": "plan", "value": "pro", "operator": "exact"}],
        ),
        (
            "a group filter without a group type",
            [{"type": "group", "key": "plan", "value": "pro", "operator": "exact"}],
        ),
        (
            "an event filter on an AI property the shared events table does not store",
            [{"type": "event", "key": "$ai_input", "operator": "is_set"}],
        ),
    ]
)
def test_a_selection_rejects_filters_it_cannot_apply(_name: str, filters: list[dict[str, Any]]) -> None:
    with pytest.raises(InvalidTraceSelectionError):
        selection_with(*filters)


@parameterized.expand(
    [
        (
            "properties",
            {
                "properties": (
                    _PROPERTY_FILTER.validate_python({"type": "event", "key": "k", "operator": "exact", "value": "v"}),
                )
            },
        ),
        ("search", {"search": "refund"}),
        ("person_id", {"person_id": "person-1"}),
        ("error", {"error": "Rate limit reached"}),
        ("tool", {"tool": "search_docs"}),
        ("failed_tool", {"failed_tool": "search_docs"}),
        ("group", {"group": TraceGroupScope(key="acme", type_index=0)}),
        ("quick_filter", {"quick_filter": "errors"}),
        ("filter_test_accounts", {"filter_test_accounts": True}),
    ]
)
def test_session_scope_rejects_list_filters(_name: str, filters: dict[str, Any]) -> None:
    with pytest.raises(InvalidTraceSelectionError):
        TraceSelection(window=WINDOW, session_id="session-1", **filters)


@parameterized.expand(
    [
        (f"{scope} {name}", {scope: value})
        for scope in ("error", "tool", "failed_tool")
        for name, value in (("empty", ""), ("whitespace", " \t"))
    ]
)
def test_a_blank_scope_is_refused(_name: str, scope: dict[str, Any]) -> None:
    with pytest.raises(InvalidTraceSelectionError):
        TraceSelection(window=WINDOW, **scope)


def test_session_scope_accepts_window_and_support_flag() -> None:
    selection = TraceSelection(
        window=WINDOW, session_id="session-1", include_support_traces=True, filter_test_accounts=False
    )
    assert selection.session_id == "session-1"
