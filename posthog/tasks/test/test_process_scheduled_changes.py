from datetime import datetime, timedelta, UTC
from posthog.models import ScheduledChange, FeatureFlag
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from posthog.tasks.process_scheduled_changes import process_scheduled_changes
from freezegun import freeze_time


class TestProcessScheduledChanges(APIBaseTest, QueryMatchingTest):
    def test_schedule_feature_flag_set_active(self) -> None:
        feature_flag = FeatureFlag.objects.create(
            name="Flag 1",
            key="flag-1",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": True},
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.active, True)

    def test_schedule_feature_flag_add_release_condition(self) -> None:
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
            "operation": "add_release_condition",
            "value": {"groups": [new_release_condition], "payloads": {}, "multivariate": None},
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"][0], new_release_condition)

    def test_schedule_feature_flag_add_release_condition_preserve_variants(self) -> None:
        variants = [
            {
                "key": "first-variant",
                "name": "First Variant",
                "rollout_percentage": 25,
            },
            {
                "key": "second-variant",
                "name": "Second Variant",
                "rollout_percentage": 75,
            },
        ]

        feature_flag = FeatureFlag.objects.create(
            name="Flag 1",
            key="flag-1",
            active=False,
            team=self.team,
            created_by=self.user,
            filters={
                "groups": [],
                "multivariate": {"variants": variants},
            },
        )

        new_release_condition = {
            "variant": None,
            "properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}],
            "rollout_percentage": 30,
        }

        payload = {
            "operation": "add_release_condition",
            "value": {"groups": [new_release_condition], "payloads": {}, "multivariate": None},
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"][0], new_release_condition)
        self.assertEqual(updated_flag.filters["multivariate"]["variants"], variants)

    def test_schedule_feature_flag_invalid_payload(self) -> None:
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
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"], [])

        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)
        self.assertEqual(updated_scheduled_change.failure_reason, "Invalid payload")

    @snapshot_postgres_queries
    @freeze_time("2023-12-21T09:00:00Z")
    def test_schedule_feature_flag_multiple_changes(self) -> None:
        feature_flag = FeatureFlag.objects.create(
            name="Flag",
            key="flag-1",
            active=True,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        # Create 4 scheduled changes
        # 1. Due in the past
        change_past_condition = {
            "properties": [{"key": "$geoip_city_name", "value": ["Sydney"], "operator": "exact", "type": "person"}],
            "rollout_percentage": 50,
            "variant": None,
        }
        change_past = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={
                "operation": "add_release_condition",
                "value": {"groups": [change_past_condition], "multivariate": None, "payloads": {}},
            },
            scheduled_at=(datetime.now(UTC) - timedelta(hours=1)),
        )

        # 2. Due in the past and already executed
        change_past_executed_at = datetime.now(UTC) - timedelta(hours=5)
        change_past_executed = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=change_past_executed_at,
            executed_at=change_past_executed_at,
        )

        # 3. Due exactly now
        change_due_now_condition = {
            "properties": [{"key": "$geoip_city_name", "value": ["New York"], "operator": "exact", "type": "person"}],
            "rollout_percentage": 75,
            "variant": None,
        }
        change_due_now = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={
                "operation": "add_release_condition",
                "value": {"groups": [change_due_now_condition], "multivariate": None, "payloads": {}},
            },
            scheduled_at=datetime.now(UTC),
        )

        # 4. Due in the future
        change_due_future = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=(datetime.now(UTC) + timedelta(hours=1)),
        )

        process_scheduled_changes()

        # Refresh change records
        change_past = ScheduledChange.objects.get(id=change_past.id)
        change_past_executed = ScheduledChange.objects.get(id=change_past_executed.id)
        change_due_now = ScheduledChange.objects.get(id=change_due_now.id)
        change_due_future = ScheduledChange.objects.get(id=change_due_future.id)

        # Changes due have been marked executed
        self.assertIsNotNone(change_past.executed_at)
        self.assertIsNotNone(change_due_now.executed_at)

        # Other changes have not been executed
        self.assertEqual(change_past_executed.executed_at, change_past_executed_at)
        self.assertIsNone(change_due_future.executed_at)

        # The changes due have been propagated in the correct order (oldest scheduled_at first)
        updated_flag = FeatureFlag.objects.get(key="flag-1")
        self.assertEqual(updated_flag.filters["groups"], [change_past_condition, change_due_now_condition])
