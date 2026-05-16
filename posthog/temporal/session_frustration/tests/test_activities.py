from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.session_frustration.activities import (
    _session_dedup_key,
    emit_frustration_events_activity,
    filter_already_emitted_activity,
    get_opted_in_team_ids_activity,
    query_frustrated_sessions_activity,
)
from posthog.temporal.session_frustration.constants import EVENT_NAME, EVENT_SOURCE
from posthog.temporal.session_frustration.types import FrustratedSession, TeamWorkflowInputs


def _make_session(
    session_id: str = "session_1",
    distinct_id: str = "user_1",
    frustration_score: int = 10,
    rage_click_count: int = 3,
    exception_count: int = 0,
    console_error_count: int = 1,
    duration_seconds: int = 300,
    first_url: str = "https://app.example.com",
) -> FrustratedSession:
    return FrustratedSession(
        session_id=session_id,
        distinct_id=distinct_id,
        frustration_score=frustration_score,
        rage_click_count=rage_click_count,
        exception_count=exception_count,
        console_error_count=console_error_count,
        duration_seconds=duration_seconds,
        first_url=first_url,
        session_start=datetime(2026, 4, 13, 10, 0, 0, tzinfo=UTC),
    )


class TestGetOptedInTeamIds:
    @pytest.mark.asyncio
    async def test_returns_enabled_teams(self):
        with patch("posthog.temporal.session_frustration.activities.Team") as mock_team:
            mock_qs = MagicMock()
            mock_qs.values_list.return_value.iterator.return_value = [(1, "token_1"), (2, "token_2")]
            mock_team.objects.filter.return_value = mock_qs

            result = await get_opted_in_team_ids_activity()

            assert result == [(1, "token_1"), (2, "token_2")]
            mock_team.objects.filter.assert_called_once_with(frustration_detection_enabled=True)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_teams(self):
        with patch("posthog.temporal.session_frustration.activities.Team") as mock_team:
            mock_qs = MagicMock()
            mock_qs.values_list.return_value.iterator.return_value = []
            mock_team.objects.filter.return_value = mock_qs

            result = await get_opted_in_team_ids_activity()

            assert result == []


class TestQueryFrustratedSessions:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_frustration_events(self):
        with patch("posthog.temporal.session_frustration.activities.sync_execute") as mock_execute:
            mock_execute.return_value = []

            result = await query_frustrated_sessions_activity(TeamWorkflowInputs(team_id=1, api_token="test_token"))

            assert result == []
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_enriches_with_session_metadata(self):
        with patch("posthog.temporal.session_frustration.activities.sync_execute") as mock_execute:
            session_start = datetime(2026, 4, 13, 10, 0, 0, tzinfo=UTC)
            mock_execute.side_effect = [
                # First call: frustration query
                [("session_abc", "user_1", 9, 3, 0)],
                # Second call: metadata query
                [("session_abc", session_start, 300, 2, "https://app.example.com")],
            ]

            result = await query_frustrated_sessions_activity(TeamWorkflowInputs(team_id=1, api_token="test_token"))

            assert len(result) == 1
            assert result[0].session_id == "session_abc"
            assert result[0].distinct_id == "user_1"
            assert result[0].frustration_score == 9
            assert result[0].rage_click_count == 3
            assert result[0].duration_seconds == 300
            assert result[0].console_error_count == 2

    @pytest.mark.asyncio
    async def test_filters_out_active_sessions(self):
        with patch("posthog.temporal.session_frustration.activities.sync_execute") as mock_execute:
            mock_execute.side_effect = [
                # First call: frustration query finds sessions
                [("session_active", "user_1", 9, 3, 0)],
                # Second call: metadata query returns empty (session still active)
                [],
            ]

            result = await query_frustrated_sessions_activity(TeamWorkflowInputs(team_id=1, api_token="test_token"))

            assert result == []


class TestFilterAlreadyEmitted:
    @pytest.mark.asyncio
    async def test_filters_already_emitted_sessions(self):
        session1 = _make_session(session_id="s1", distinct_id="u1")
        session2 = _make_session(session_id="s2", distinct_id="u2")

        with patch("posthog.temporal.session_frustration.activities.cache") as mock_cache:

            def mock_get(key):
                if key == _session_dedup_key(1, "s1"):
                    return 1
                return None

            mock_cache.get.side_effect = mock_get

            result = await filter_already_emitted_activity(1, [session1, session2])
            assert len(result) == 1
            assert result[0].session_id == "s2"

    @pytest.mark.asyncio
    async def test_filters_person_at_frequency_cap(self):
        session1 = _make_session(session_id="s1", distinct_id="u1")

        with patch("posthog.temporal.session_frustration.activities.cache") as mock_cache:

            def mock_get(key):
                if "session:" in key:
                    return None  # Session not emitted
                if "person:" in key:
                    return 1  # Person at frequency cap
                return None

            mock_cache.get.side_effect = mock_get

            result = await filter_already_emitted_activity(1, [session1])
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_returns_all_when_none_emitted(self):
        sessions = [
            _make_session(session_id="s1"),
            _make_session(session_id="s2"),
            _make_session(session_id="s3"),
        ]

        with patch("posthog.temporal.session_frustration.activities.cache") as mock_cache:
            mock_cache.get.return_value = None

            result = await filter_already_emitted_activity(1, sessions)
            assert len(result) == 3


class TestEmitFrustrationEvents:
    @pytest.mark.asyncio
    async def test_emits_events_and_sets_dedup_keys(self):
        sessions = [_make_session(session_id="s1", distinct_id="u1")]

        with patch("posthog.temporal.session_frustration.activities.capture_internal") as mock_capture:
            with patch("posthog.temporal.session_frustration.activities.cache") as mock_cache:
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                result = await emit_frustration_events_activity(1, "test_token", sessions)

                assert result == 1

                mock_capture.assert_called_once()
                call_kwargs = mock_capture.call_args[1]
                assert call_kwargs["event_name"] == EVENT_NAME
                assert call_kwargs["event_source"] == EVENT_SOURCE
                assert call_kwargs["token"] == "test_token"
                assert call_kwargs["distinct_id"] == "u1"
                assert call_kwargs["process_person_profile"] is False
                props = call_kwargs["properties"]
                assert props["$session_id"] == "s1"
                assert props["frustration_score"] == 10
                assert props["rage_click_count"] == 3
                assert props["detection_method"] == "heuristic_v1"

                # Should set both session and person dedup keys
                assert mock_cache.set.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        sessions = [
            _make_session(session_id="s1", distinct_id="u1"),
            _make_session(session_id="s2", distinct_id="u2"),
        ]

        call_count = 0

        with patch("posthog.temporal.session_frustration.activities.capture_internal") as mock_capture:
            with patch("posthog.temporal.session_frustration.activities.cache"):

                def side_effect(**kwargs):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        raise Exception("Network error")
                    return MagicMock(status_code=200, raise_for_status=MagicMock())

                mock_capture.side_effect = side_effect

                result = await emit_frustration_events_activity(1, "test_token", sessions)

                # First fails, second succeeds
                assert result == 1
                assert mock_capture.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_sessions(self):
        with patch("posthog.temporal.session_frustration.activities.capture_internal") as mock_capture:
            with patch("posthog.temporal.session_frustration.activities.cache"):
                result = await emit_frustration_events_activity(1, "test_token", [])
                assert result == 0
                mock_capture.assert_not_called()
