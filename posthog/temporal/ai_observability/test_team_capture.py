import time
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.api.capture import CaptureInternalError, CaptureInternalResult
from posthog.models.team import Team
from posthog.temporal.ai_observability.team_capture import (
    EMIT_EVENT_RETRY_POLICY,
    TOKEN_CACHE_TTL_SECONDS,
    CaptureEventDropped,
    TeamNotFound,
    TransientEmitError,
    capture_ai_internal_for_team,
    get_team_api_token,
    raise_for_emit_attempt,
    workflow_event_uuid,
)


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

    @parameterized.expand(
        [
            ("dropped", CaptureInternalResult(status_code=200, dropped=["u1"]), CaptureEventDropped),
            ("unaccounted", CaptureInternalResult(status_code=200, unaccounted=["u1"]), CaptureInternalError),
            ("retried", CaptureInternalResult(status_code=200, retried=["u1"]), CaptureInternalError),
        ]
    )
    def test_only_a_drop_raises_capture_event_dropped(self, _name, result, expected_error):
        with patch("posthog.temporal.ai_observability.team_capture.capture_ai_internal", return_value=result):
            with self.assertRaises(CaptureInternalError) as ctx:
                _emit(self.team.id)
        assert type(ctx.exception) is expected_error


def _activity_info(attempt: int, workflow_id: str = "wf-1") -> MagicMock:
    return MagicMock(attempt=attempt, workflow_id=workflow_id)


class TestEmitRetryHelpers(BaseTest):
    @parameterized.expand(
        [
            ("first_attempt", 1, TransientEmitError),
            ("second_to_last_attempt", (EMIT_EVENT_RETRY_POLICY.maximum_attempts or 0) - 1, TransientEmitError),
            ("final_attempt", EMIT_EVENT_RETRY_POLICY.maximum_attempts, CaptureInternalError),
        ]
    )
    def test_only_the_final_attempt_raises_a_reportable_error(self, _name, attempt, expected_error):
        error = CaptureInternalError("blip")
        with (
            patch("temporalio.activity.in_activity", return_value=True),
            patch("temporalio.activity.info", return_value=_activity_info(attempt)),
        ):
            with self.assertRaises(Exception) as ctx:
                raise_for_emit_attempt(error)
        assert type(ctx.exception) is expected_error

    def test_workflow_event_uuid_is_stable_per_workflow_and_kind(self):
        with patch("temporalio.activity.in_activity", return_value=True):
            with patch("temporalio.activity.info", return_value=_activity_info(1)):
                first = workflow_event_uuid("ai-tag")
            with patch("temporalio.activity.info", return_value=_activity_info(3)):
                retried = workflow_event_uuid("ai-tag")
                other_kind = workflow_event_uuid("ai-evaluation")
            with patch("temporalio.activity.info", return_value=_activity_info(1, workflow_id="wf-2")):
                other_workflow = workflow_event_uuid("ai-tag")
        assert first == retried
        assert len({first, other_kind, other_workflow}) == 3
