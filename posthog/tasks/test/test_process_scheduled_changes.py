from datetime import datetime, timedelta, timezone
from posthog.models import ScheduledChange, FeatureFlag
from posthog.test.base import APIBaseTest
from posthog.tasks.process_scheduled_changes import process_scheduled_changes


class TestProcessScheduledChanges(APIBaseTest):
    def test_schedule_feature_flag_set_active(self):
        feature_flag = FeatureFlag.objects.create(
            name="Flag 1",
            key="flag-1",
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            team=self.team,
            created_by=self.user,
        )

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"field": "active", "value": True},
            scheduled_at=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.active, True)

    def test_schedule_feature_flag_add_release_condition(self):
        feature_flag = FeatureFlag.objects.create(
            name="Flag 1",
            key="flag-1",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        new_release_condition = {
            "variant": None,
            "properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}],
            "rollout_percentage": 30,
        }

        payload = {
            "field": "filters",
            "value": {"groups": [new_release_condition], "payloads": {}, "multivariate": None},
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"][0], new_release_condition)

    def test_schedule_feature_flag_invalid_payload(self):
        feature_flag = FeatureFlag.objects.create(
            name="Flag 1",
            key="flag-1",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        payload = {"foo": "bar"}

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"], [])

        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)
        self.assertEqual(updated_scheduled_change.failure_reason, "Invalid payload")
