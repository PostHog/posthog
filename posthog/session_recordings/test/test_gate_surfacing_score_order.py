from types import SimpleNamespace
from typing import cast

from unittest import TestCase, mock

from parameterized import parameterized

from posthog.schema import RecordingOrder, RecordingsQuery

from posthog.models import User
from posthog.session_recordings.utils import gate_replay_relevance


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
            gate_replay_relevance(query, _user())
            assert query.order == expected
            feature_enabled.assert_not_called()

    @parameterized.expand(
        [
            ("surfacing_flag_enabled", True, RecordingOrder.SURFACING_SCORE),
            ("surfacing_flag_disabled", False, RecordingOrder.START_TIME),
        ]
    )
    def test_surfacing_score_kept_only_for_rollout(self, _name, surfacing_enabled, expected):
        with mock.patch(
            "posthog.session_recordings.utils.posthoganalytics.feature_enabled", return_value=surfacing_enabled
        ):
            query = _query(RecordingOrder.SURFACING_SCORE)
            gate_replay_relevance(query, _user())
            assert query.order == expected

    @parameterized.expand(
        [
            ("test_variant", "test", True),
            ("control_variant", "control", False),
            ("missing_variant", None, False),
        ]
    )
    def test_recommended_filter_kept_only_for_test_variant(self, _name, variant, expected):
        with mock.patch("posthog.session_recordings.utils.posthoganalytics.get_feature_flag", return_value=variant):
            query = RecordingsQuery(recommended_only=True)
            gate_replay_relevance(query, _user())
            assert query.recommended_only is expected

    def test_relevance_features_fall_back_without_a_user(self):
        with (
            mock.patch("posthog.session_recordings.utils.posthoganalytics.feature_enabled") as feature_enabled,
            mock.patch("posthog.session_recordings.utils.posthoganalytics.get_feature_flag") as get_feature_flag,
        ):
            query = RecordingsQuery(order=RecordingOrder.SURFACING_SCORE, recommended_only=True)
            gate_replay_relevance(query, None)
            assert query.order == RecordingOrder.START_TIME
            assert query.recommended_only is False
            feature_enabled.assert_not_called()
            get_feature_flag.assert_not_called()
