import time
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.api.capture import CaptureInternalError
from posthog.models.team import Team
from posthog.temporal.ai_observability.team_capture import (
    TOKEN_CACHE_TTL_SECONDS,
    TeamNotFound,
    capture_internal_for_team,
    get_team_api_token,
)


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

    def test_expired_ttl_picks_up_a_rotated_token(self):
        # Capture accepts stale tokens at the edge, so TTL expiry is the only path through
        # which a rotated token recovers.
        get_team_api_token(self.team.id)
        Team.objects.filter(id=self.team.id).update(api_token="phc_rotated")
        with patch(
            "posthog.temporal.ai_observability.team_capture.time.monotonic",
            return_value=time.monotonic() + TOKEN_CACHE_TTL_SECONDS + 1,
        ):
            assert get_team_api_token(self.team.id) == "phc_rotated"

    def test_auth_rejection_invalidates_the_cached_token(self):
        get_team_api_token(self.team.id)
        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            side_effect=CaptureInternalError("unauthorized", status_code=401),
        ):
            with self.assertRaises(CaptureInternalError):
                _emit(self.team.id)

        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            return_value=MagicMock(raise_for_status=MagicMock()),
        ) as mock_capture:
            with self.assertNumQueries(1):
                _emit(self.team.id)
        assert mock_capture.call_args[1]["token"] == self.team.api_token

    @parameterized.expand(
        [
            ("billing_limit_402", CaptureInternalError("quota limited", status_code=402)),
            ("capture_5xx", CaptureInternalError("whole-request failure", status_code=502)),
            ("transport_error", CaptureInternalError("timed out", status_code=0)),
        ]
    )
    def test_non_auth_capture_failure_keeps_the_cached_token(self, _name, error):
        get_team_api_token(self.team.id)
        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            side_effect=error,
        ):
            with self.assertRaises(CaptureInternalError):
                _emit(self.team.id)

        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_internal",
            return_value=MagicMock(raise_for_status=MagicMock()),
        ):
            with self.assertNumQueries(0):
                _emit(self.team.id)
