from freezegun import freeze_time

from ee.tasks.auto_rollback_feature_flag import check_condition
from posthog.models.feature_flag import FeatureFlag
from posthog.test.base import APIBaseTest, _create_event


class AutoRollbackTest(APIBaseTest):
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
            auto_rollback=True,
            rollback_conditions=[rollback_condition],
        )

        self.assertEqual(check_condition(rollback_condition, flag), False)

    def test_check_condition_valid(self):
        rollback_condition = {
            "threshold": 5,
            "threshold_metric": {
                "insight": "trends",
                "events": [{"order": 0, "id": "$pageview"}],
            },
            "operator": "lt",
            "threshold_type": "insight",
        }

        for _ in range(10):
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
                auto_rollback=True,
                rollback_conditions=[rollback_condition],
            )

        with freeze_time("2021-08-23T20:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), False)

        # Go another day with 0 events
        with freeze_time("2021-08-25T20:00:00.000Z"):
            self.assertEqual(check_condition(rollback_condition, flag), True)
