from types import SimpleNamespace
from typing import cast

from unittest import TestCase, mock

from parameterized import parameterized

from posthog.schema import RecordingOrder, RecordingsQuery

from posthog.models import User
from posthog.session_recordings.utils import gate_surfacing_score_order


def _query(order: RecordingOrder | None) -> RecordingsQuery:
    return RecordingsQuery(order=order)


def _user() -> User:
    # The gate only reads `distinct_id` and `email`, so a lightweight stand-in avoids touching the DB.
    return cast(User, SimpleNamespace(distinct_id="abc123", email="nicholas.w@posthog.com"))


class TestGateSurfacingScoreOrder(TestCase):
    @parameterized.expand(
        [
            ("start_time_untouched", RecordingOrder.START_TIME, RecordingOrder.START_TIME),
            ("activity_score_untouched", RecordingOrder.ACTIVITY_SCORE, RecordingOrder.ACTIVITY_SCORE),
        ]
    )
    def test_non_surfacing_orders_never_evaluate_the_flag(self, _name, order, expected):
        with mock.patch("posthog.session_recordings.utils.posthoganalytics.feature_enabled") as feature_enabled:
            query = _query(order)
            gate_surfacing_score_order(query, _user())
            assert query.order == expected
            feature_enabled.assert_not_called()

    @parameterized.expand(
        [
            ("surfacing_flag_enabled", True, None, RecordingOrder.SURFACING_SCORE),
            ("experiment_test_arm", False, "test", RecordingOrder.SURFACING_SCORE),
            ("experiment_control_arm", False, "control", RecordingOrder.START_TIME),
            ("neither_enabled", False, None, RecordingOrder.START_TIME),
        ]
    )
    def test_surfacing_score_kept_only_for_rollout_or_experiment_test_arm(
        self, _name, surfacing_enabled, experiment_variant, expected
    ):
        with (
            mock.patch(
                "posthog.session_recordings.utils.posthoganalytics.feature_enabled", return_value=surfacing_enabled
            ),
            mock.patch(
                "posthog.session_recordings.utils.posthoganalytics.get_feature_flag", return_value=experiment_variant
            ),
        ):
            query = _query(RecordingOrder.SURFACING_SCORE)
            gate_surfacing_score_order(query, _user())
            assert query.order == expected

    def test_surfacing_score_falls_back_without_a_user(self):
        with mock.patch("posthog.session_recordings.utils.posthoganalytics.feature_enabled") as feature_enabled:
            query = _query(RecordingOrder.SURFACING_SCORE)
            gate_surfacing_score_order(query, None)
            assert query.order == RecordingOrder.START_TIME
            feature_enabled.assert_not_called()
