from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import exceptions

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents, SessionsWithTimestamps

from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps_dropping_missing

MIN_TS = datetime(2026, 7, 29, 8, 0, 0, tzinfo=UTC)
MAX_TS = datetime(2026, 7, 29, 9, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "requested,found_in_db,expected_found,expected_missing",
    [
        # One recording dropped out between validation reads: keep the rest instead of failing the batch
        (["s-1", "s-2", "s-3"], {"s-1", "s-3"}, ["s-1", "s-3"], ["s-2"]),
        (["s-1", "s-2"], {"s-1", "s-2"}, ["s-1", "s-2"], []),
        # Duplicate requested IDs must not spawn duplicate summarization tasks: dedupe found and missing in order
        (["s-1", "s-1", "s-2", "s-2", "s-3"], {"s-1"}, ["s-1"], ["s-2", "s-3"]),
    ],
)
def test_find_sessions_timestamps_dropping_missing(
    requested: list[str],
    found_in_db: set[str],
    expected_found: list[str],
    expected_missing: list[str],
) -> None:
    query_result = SessionsWithTimestamps(session_ids=found_in_db, min_timestamp=MIN_TS, max_timestamp=MAX_TS)
    with patch.object(SessionReplayEvents, "sessions_found_with_timestamps", return_value=query_result):
        sessions = find_sessions_timestamps_dropping_missing(session_ids=requested, team=MagicMock(id=1))
    assert sessions.found_session_ids == expected_found
    assert sessions.missing_session_ids == expected_missing
    assert sessions.min_timestamp == MIN_TS
    assert sessions.max_timestamp == MAX_TS


@pytest.mark.parametrize(
    "found_in_db,min_timestamp,max_timestamp,expected_error",
    [
        (set(), None, None, "Session recordings not found for the following IDs.*s-1, s-2"),
        # Recordings were found, so the error has to name the timestamps instead of listing no IDs at all
        ({"s-1"}, None, MAX_TS, "Failed to get min .* or max .* timestamps for sessions: s-1"),
    ],
)
def test_find_sessions_timestamps_dropping_missing_raises(
    found_in_db: set[str],
    min_timestamp: datetime | None,
    max_timestamp: datetime | None,
    expected_error: str,
) -> None:
    query_result = SessionsWithTimestamps(
        session_ids=found_in_db, min_timestamp=min_timestamp, max_timestamp=max_timestamp
    )
    with patch.object(SessionReplayEvents, "sessions_found_with_timestamps", return_value=query_result):
        with pytest.raises(exceptions.ValidationError, match=expected_error):
            find_sessions_timestamps_dropping_missing(session_ids=["s-1", "s-2"], team=MagicMock(id=1))
