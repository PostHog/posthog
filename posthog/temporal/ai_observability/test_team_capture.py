from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.temporal.ai_observability.team_capture import TeamNotFound, capture_internal_for_team, get_team_api_token


def _emit(team_id: int) -> None:
    capture_internal_for_team(
        team_id=team_id,
        event_name="$ai_evaluation",
        event_source="llm_analytics_evaluation",
        distinct_id="user-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        properties={},
    )


class TestTeamCapture(BaseTest):
    def test_token_is_read_from_postgres_only_once_per_team(self):
        assert get_team_api_token(self.team.id) == self.team.api_token
        with self.assertNumQueries(0):
            assert get_team_api_token(self.team.id) == self.team.api_token

    def test_missing_team_raises(self):
        with self.assertRaises(TeamNotFound):
            get_team_api_token(self.team.id + 10_000)

    def test_capture_failure_invalidates_the_cached_token(self):
        # A rotated token has to recover before the TTL expires, so a rejected capture drops
        # the cache entry and the next emit re-reads Postgres.
        get_team_api_token(self.team.id)
        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            side_effect=Exception("rejected"),
        ):
            with self.assertRaises(Exception):
                _emit(self.team.id)

        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            return_value=MagicMock(raise_for_status=MagicMock()),
        ) as mock_capture:
            with self.assertNumQueries(1):
                _emit(self.team.id)
        assert mock_capture.call_args[1]["token"] == self.team.api_token
