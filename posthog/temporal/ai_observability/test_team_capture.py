import time
import dataclasses
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.api.capture import CaptureInternalError
from posthog.models.team import Team
from posthog.temporal.ai_observability.team_capture import (
    EMIT_EVENT_RETRY_POLICY,
    EMIT_EVENT_SCHEDULE_TO_CLOSE_TIMEOUT,
    TOKEN_CACHE_TTL_SECONDS,
    TeamNotFound,
    capture_ai_internal_for_team,
    get_team_api_token,
    raise_emit_failure,
)
from posthog.temporal.common.errors import NonReportableApplicationError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _emit(team_id: int) -> None:
    capture_ai_internal_for_team(
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
            "posthog.temporal.ai_observability.team_capture.capture_ai_internal",
            side_effect=CaptureInternalError("unauthorized", status_code=401),
        ):
            with self.assertRaises(CaptureInternalError):
                _emit(self.team.id)

        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_ai_internal",
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
            "posthog.temporal.ai_observability.team_capture.capture_ai_internal",
            side_effect=error,
        ):
            with self.assertRaises(CaptureInternalError):
                _emit(self.team.id)

        with patch(
            "posthog.temporal.ai_observability.team_capture.capture_ai_internal",
            return_value=MagicMock(raise_for_status=MagicMock()),
        ):
            with self.assertNumQueries(0):
                _emit(self.team.id)


class TestRaiseEmitFailure(SimpleTestCase):
    @parameterized.expand(
        [
            ("retry_left", 1, 3600, NonReportableApplicationError),
            ("final_attempt", EMIT_EVENT_RETRY_POLICY.maximum_attempts, 3600, CaptureInternalError),
            ("backoff_lands_past_deadline", 1, 2, CaptureInternalError),
        ]
    )
    def test_only_the_final_attempt_raises_a_reportable_error(
        self, _name, attempt, seconds_to_deadline, expected_error
    ):
        schedule_to_close = EMIT_EVENT_SCHEDULE_TO_CLOSE_TIMEOUT
        env = ActivityEnvironment()
        env.info = dataclasses.replace(
            env.info,
            attempt=attempt,
            retry_policy=EMIT_EVENT_RETRY_POLICY,
            schedule_to_close_timeout=schedule_to_close,
            scheduled_time=NOW - schedule_to_close + timedelta(seconds=seconds_to_deadline),
        )
        with time_machine.travel(NOW, tick=False), self.assertRaises(Exception) as ctx:
            env.run(raise_emit_failure, CaptureInternalError("blip"))
        assert type(ctx.exception) is expected_error
