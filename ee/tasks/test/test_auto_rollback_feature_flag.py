from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from posthog.models.feature_flag import FeatureFlag

from ee.tasks.auto_rollback_feature_flag import (
    calculate_rolling_average,
    check_condition,
    check_feature_flag_rollback_conditions,
)


class AutoRollbackTest(ClickhouseTestMixin, APIBaseTest):
    def test_calculate_rolling_average(self):
        threshold_metric = {
            "insight": "trends",
            "events": [{"order": 0, "id": "$pageview"}],
        }

        with freeze_time("2021-08-21T20:00:00.000Z"):
            for _ in range(70):
                _create_event(
                    event="$pageview",
                    distinct_id="1",
                    team=self.team,
                    timestamp="2021-08-21 05:00:00",
                    properties={"prop": 1},
                )

                _create_event(
                    event="$pageview",
                    distinct_id="1",
                    team=self.team,
                    timestamp="2021-08-22 05:00:00",
                    properties={"prop": 1},
                )
        with freeze_time("2021-08-21T21:00:00.000Z"):
            self.assertEqual(
                calculate_rolling_average(
                    threshold_metric=threshold_metric,
                    team=self.team,
                    timezone="UTC",
                ),
                10,  # because we have 70 events in the last 7 days
            )

        with freeze_time("2021-08-22T21:00:00.000Z"):
            self.assertEqual(
                calculate_rolling_average(
                    threshold_metric=threshold_metric,
                    team=self.team,
                    timezone="UTC",
                ),
                20,  # because we have 140 events in the last 7 days
            )

    def test_check_condition(self):
        rollback_condition = {
            "threshold": 10,
            "threshold_metric": {
                "insight": "trends",
                "events": [{"order": 0, "id": "$pageview"}],
            },
            "operator": "lt",
            "threshold_type": "insight",
        }

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test-ff",
            rollout_percentage=50,
            rollback_conditions=[rollback_condition],
        )

        self.assertEqual(check_condition(rollback_condition, flag), True)

    def test_check_condition_valid(self):
        rollback_condition = {
            "threshold": 15,
            "threshold_metric": {
                "insight": "trends",
                "events": [{"order": 0, "id": "$pageview"}],
            },
            "operator": "gt",
            "threshold_type": "insight",
        }

        for _ in range(70):
            _create_event(
                event="$pageview",
                distinct_id="1",
                team=self.team,
                timestamp="2021-08-21 00:00:00",
                properties={"prop": 1},
            )
            _create_event(
                event="$pageview",
                distinct_id="1",
                team=self.team,
                timestamp="2021-08-22 00:00:00",
                properties={"prop": 1},
            )

        with freeze_time("2021-08-21T20:00:00.000Z"):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="test-ff",
                rollout_percentage=50,
                rollback_conditions=[rollback_condition],
            )

        with freeze_time("2021-08-21T20:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), False)

        # Go another day with 0 events
        with freeze_time("2021-08-22T20:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), True)

    def test_feature_flag_rolledback(self):
        rollback_condition = {
            "threshold": 15,
            "threshold_metric": {
                "insight": "trends",
                "events": [{"order": 0, "id": "$pageview"}],
            },
            "operator": "gt",
            "threshold_type": "insight",
        }

        for _ in range(70):
            _create_event(
                event="$pageview",
                distinct_id="1",
                team=self.team,
                timestamp="2021-08-21 00:00:00",
                properties={"prop": 1},
            )
            _create_event(
                event="$pageview",
                distinct_id="1",
                team=self.team,
                timestamp="2021-08-22 00:00:00",
                properties={"prop": 1},
            )

        with freeze_time("2021-08-21T00:00:00.000Z"):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="test-ff",
                rollout_percentage=50,
                rollback_conditions=[rollback_condition],
            )

        flag = FeatureFlag.objects.get(pk=flag.pk)
        self.assertEqual(flag.performed_rollback, None)
        self.assertEqual(flag.active, True)

        with freeze_time("2021-08-23T20:00:00.000Z"):
            check_feature_flag_rollback_conditions(feature_flag_id=flag.pk)
            flag = FeatureFlag.objects.get(pk=flag.pk)
            self.assertEqual(flag.performed_rollback, True)
            self.assertEqual(flag.active, False)

    @patch("ee.tasks.auto_rollback_feature_flag.get_stats_for_timerange")
    def test_check_condition_sentry(self, stats_for_timerange):
        rollback_condition = {
            "threshold": 1.25,
            "threshold_metric": {},
            "operator": "gt",
            "threshold_type": "sentry",
        }

        with freeze_time("2021-08-21T20:00:00.000Z"):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="test-ff",
                rollout_percentage=50,
                rollback_conditions=[rollback_condition],
            )

        stats_for_timerange.return_value = (100, 130)
        with freeze_time("2021-08-23T20:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), True)
            stats_for_timerange.assert_called_once_with(
                "2021-08-21T20:00:00",
                "2021-08-22T20:00:00",
                "2021-08-22T20:00:00",
                "2021-08-23T20:00:00",
            )

        stats_for_timerange.reset_mock()
        stats_for_timerange.return_value = (100, 120)
        with freeze_time("2021-08-25T13:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), False)
            stats_for_timerange.assert_called_once_with(
                "2021-08-21T20:00:00",
                "2021-08-22T20:00:00",
                "2021-08-24T13:00:00",
                "2021-08-25T13:00:00",
            )
