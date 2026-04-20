import pytest

from parameterized import parameterized

from posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters import (
    _determine_cluster_weight_as_signal,
)


class TestDetermineClusterWeightAsSignal:
    @parameterized.expand(
        [
            # (actionable, relevant_users, active_users, expected_weight)
            # Non-actionable always returns 0.1
            ("not_actionable_small_team", False, 5, 10, 0.1),
            ("not_actionable_large_team", False, 500, 1000, 0.1),
            ("not_actionable_all_affected", False, 10, 10, 0.1),
            # Edge cases: no active users falls back to 0.1
            ("actionable_zero_active", True, 5, 0, 0.1),
            ("actionable_negative_active", True, 5, -1, 0.1),
            # Startup (10 active users): each user is 10% of the base
            ("startup_1_of_10", True, 1, 10, pytest.approx(0.1 + 0.9 * (0.1**0.5), abs=0.01)),
            ("startup_5_of_10", True, 5, 10, pytest.approx(0.1 + 0.9 * (0.5**0.5), abs=0.01)),
            ("startup_all_10", True, 10, 10, 1.0),
            # Medium team (100 active users)
            ("medium_5_of_100", True, 5, 100, pytest.approx(0.1 + 0.9 * (0.05**0.5), abs=0.01)),
            ("medium_50_of_100", True, 50, 100, pytest.approx(0.1 + 0.9 * (0.5**0.5), abs=0.01)),
            ("medium_all_100", True, 100, 100, 1.0),
            # Large team (10000 active users)
            ("large_5_of_10000", True, 5, 10000, pytest.approx(0.1 + 0.9 * (0.0005**0.5), abs=0.01)),
            ("large_1000_of_10000", True, 1000, 10000, pytest.approx(0.1 + 0.9 * (0.1**0.5), abs=0.01)),
            ("large_all_10000", True, 10000, 10000, 1.0),
            # Relevant > active (clamped to 1.0 impact ratio)
            ("overcounted", True, 15, 10, 1.0),
        ],
    )
    def test_weight_calculation(self, _name, actionable, relevant_users, active_users, expected_weight):
        weight = _determine_cluster_weight_as_signal(
            actionable=actionable,
            relevant_user_count=relevant_users,
            active_users_in_period=active_users,
        )
        assert weight == expected_weight

    def test_weight_increases_with_impact_ratio(self):
        """Weight is monotonically increasing with the fraction of affected users."""
        weights = [
            _determine_cluster_weight_as_signal(
                actionable=True,
                relevant_user_count=n,
                active_users_in_period=100,
            )
            for n in [1, 5, 10, 25, 50, 100]
        ]
        for i in range(1, len(weights)):
            assert weights[i] > weights[i - 1]

    def test_same_ratio_same_weight_regardless_of_team_size(self):
        """50% impact produces the same weight whether the team is 10 or 10000 users."""
        weight_small = _determine_cluster_weight_as_signal(
            actionable=True, relevant_user_count=5, active_users_in_period=10
        )
        weight_large = _determine_cluster_weight_as_signal(
            actionable=True, relevant_user_count=5000, active_users_in_period=10000
        )
        assert weight_small == pytest.approx(weight_large, abs=0.001)
