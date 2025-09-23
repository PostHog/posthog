import json
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries

from posthog.models import FeatureFlag, ScheduledChange
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.tasks.process_scheduled_changes import process_scheduled_changes


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

        # Parse the JSON failure_reason to check the error message
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        failure_reason = updated_scheduled_change.failure_reason
        assert failure_reason is not None  # For mypy type narrowing
        failure_data = json.loads(failure_reason)
        self.assertEqual(failure_data["error"], "Invalid payload")
        self.assertEqual(failure_data["error_type"], "Exception")
        self.assertIn("hostname", failure_data)
        # Note: scheduled_change_id, model, team_id, etc. are already in the ScheduledChange table columns

        # Verify failure_count was incremented
        self.assertEqual(updated_scheduled_change.failure_count, 1)

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

    def test_scheduled_changes_create_activity_log_with_trigger(self) -> None:
        """Test that scheduled changes create activity logs with trigger information while preserving user attribution"""
        feature_flag = FeatureFlag.objects.create(
            name="Test Flag",
            key="test-flag",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": True},
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        # Clear any existing activity logs
        ActivityLog.objects.filter(
            scope="FeatureFlag",
            item_id=str(feature_flag.id),
        ).delete()

        # Process the scheduled change
        process_scheduled_changes()

        # Verify the flag was updated
        updated_flag = FeatureFlag.objects.get(key="test-flag")
        self.assertEqual(updated_flag.active, True)

        # Verify scheduled change was marked as executed
        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)
        self.assertIsNotNone(updated_scheduled_change.executed_at)
        self.assertIsNone(updated_scheduled_change.failure_reason)

        # Verify activity log entry was created with trigger information
        activity_logs = ActivityLog.objects.filter(
            scope="FeatureFlag", item_id=str(feature_flag.id), activity="updated"
        )

        self.assertEqual(activity_logs.count(), 1)
        activity_log = activity_logs.first()
        self.assertIsNotNone(activity_log)
        assert activity_log is not None  # for mypy

        # Check that it's NOT marked as a system activity (scheduled changes preserve user attribution)
        self.assertFalse(activity_log.is_system)

        # Check that user attribution is preserved
        self.assertEqual(activity_log.user, self.user)

        # Check that trigger information identifies this as a scheduled change
        self.assertIsNotNone(activity_log.detail)
        trigger = activity_log.detail.get("trigger")
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger["job_type"], "scheduled_change")
        self.assertEqual(trigger["job_id"], str(scheduled_change.id))

        # Verify the change details are correct
        self.assertIsNotNone(activity_log.detail)
        changes = activity_log.detail.get("changes", [])
        self.assertTrue(len(changes) > 0)

        # Find the change for the 'active' field
        active_change = None
        for change in changes:
            if change.get("field") == "active":
                active_change = change
                break

        self.assertIsNotNone(active_change)
        self.assertEqual(active_change["before"], False)  # type: ignore
        self.assertEqual(active_change["after"], True)  # type: ignore

    @freeze_time("2023-12-21T09:00:00Z")
    def test_updated_at_field_tracks_processing_time(self) -> None:
        """Test that updated_at is automatically updated when scheduled changes are processed"""
        feature_flag = FeatureFlag.objects.create(
            name="Test Flag",
            key="test-flag-updated-at",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": True},
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        # Store original timestamps
        original_created_at = scheduled_change.created_at
        original_updated_at = scheduled_change.updated_at

        # Initially, created_at and updated_at should be the same due to creation time
        self.assertEqual(original_created_at, original_updated_at)

        # Advance time to simulate processing delay
        with freeze_time("2023-12-21T09:00:10Z"):
            # Process the scheduled change
            process_scheduled_changes()

            # Refresh the scheduled change from database
            updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)

            # Verify that updated_at was modified when the change was processed
            self.assertEqual(updated_scheduled_change.created_at, original_created_at)
            self.assertGreater(updated_scheduled_change.updated_at, original_updated_at)

            # Verify the change was processed successfully
            self.assertIsNotNone(updated_scheduled_change.executed_at)
            self.assertIsNone(updated_scheduled_change.failure_reason)
            self.assertEqual(updated_scheduled_change.failure_count, 0)  # No failures for successful processing

    def test_recoverable_error_allows_retry(self) -> None:
        """Test that recoverable errors don't set executed_at, allowing retries"""
        from unittest.mock import patch

        feature_flag = FeatureFlag.objects.create(
            name="Test Flag",
            key="test-recoverable-error",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": True},
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        # Mock the dispatcher to raise a recoverable error (OperationalError)
        with patch.object(FeatureFlag, "scheduled_changes_dispatcher") as mock_dispatcher:
            from django.db import OperationalError

            mock_dispatcher.side_effect = OperationalError("Connection timeout")

            # Process the scheduled change - should fail but not set executed_at
            process_scheduled_changes()

        # Refresh the scheduled change from database
        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)

        # Verify that executed_at is NOT set (allowing retries)
        self.assertIsNone(updated_scheduled_change.executed_at)
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        self.assertEqual(updated_scheduled_change.failure_count, 1)

        # Parse failure reason to verify it contains error details and retry info
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        failure_reason = updated_scheduled_change.failure_reason
        assert failure_reason is not None  # For mypy type narrowing
        failure_data = json.loads(failure_reason)
        self.assertEqual(failure_data["error_type"], "OperationalError")
        self.assertEqual(failure_data["error"], "Connection timeout")
        self.assertTrue(failure_data["will_retry"])  # Should indicate will retry
        self.assertEqual(failure_data["retry_count"], 1)
        self.assertEqual(failure_data["error_classification"], "recoverable")

    def test_unrecoverable_error_prevents_retry(self) -> None:
        """Test that unrecoverable errors set executed_at, preventing retries"""
        feature_flag = FeatureFlag.objects.create(
            name="Test Flag",
            key="test-unrecoverable-error",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        # Create a scheduled change with invalid payload (unrecoverable error)
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"invalid": "payload"},  # This will cause ValidationError
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        # Process the scheduled change - should fail and set executed_at
        process_scheduled_changes()

        # Refresh the scheduled change from database
        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)

        # Verify that executed_at IS set (preventing retries)
        self.assertIsNotNone(updated_scheduled_change.executed_at)
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        self.assertEqual(updated_scheduled_change.failure_count, 1)

        # Parse failure reason to verify it contains error details and retry info
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        failure_reason = updated_scheduled_change.failure_reason
        assert failure_reason is not None  # For mypy type narrowing
        failure_data = json.loads(failure_reason)
        self.assertEqual(failure_data["error"], "Invalid payload")
        self.assertFalse(failure_data["will_retry"])  # Should indicate won't retry
        self.assertEqual(failure_data["retry_count"], 1)
        self.assertEqual(failure_data["error_classification"], "unrecoverable")

    def test_max_retries_exceeded(self) -> None:
        """Test that changes exceeding max retries preserve actual error info"""
        from unittest.mock import patch

        from posthog.tasks.process_scheduled_changes import MAX_RETRY_ATTEMPTS

        feature_flag = FeatureFlag.objects.create(
            name="Test Flag",
            key="test-max-retries",
            active=False,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        # Create a scheduled change that's one failure away from limit
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": True},
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
            failure_count=MAX_RETRY_ATTEMPTS - 1,  # One away from limit
        )

        # Mock the dispatcher to raise a recoverable error that will hit the limit
        with patch.object(FeatureFlag, "scheduled_changes_dispatcher") as mock_dispatcher:
            from django.db import OperationalError

            mock_dispatcher.side_effect = OperationalError("Database connection lost")

            # Process the scheduled change - should hit max retry limit
            process_scheduled_changes()

        # Refresh the scheduled change from database
        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)

        # Verify that it's marked as permanently failed due to retry limit
        self.assertIsNotNone(updated_scheduled_change.executed_at)
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        self.assertEqual(updated_scheduled_change.failure_count, MAX_RETRY_ATTEMPTS)

        # Parse failure reason to verify actual error info is preserved
        failure_reason = updated_scheduled_change.failure_reason
        assert failure_reason is not None  # For mypy type narrowing
        failure_data = json.loads(failure_reason)

        # Should contain the actual error details, not just "max retries exceeded"
        self.assertEqual(failure_data["error"], "Database connection lost")
        self.assertEqual(failure_data["error_type"], "OperationalError")
        self.assertEqual(failure_data["error_classification"], "recoverable")
        self.assertFalse(failure_data["will_retry"])  # Won't retry due to limit
        self.assertTrue(failure_data["retry_exhausted"])  # Indicates limit reached
        self.assertEqual(failure_data["retry_count"], MAX_RETRY_ATTEMPTS)
        self.assertEqual(failure_data["max_retries"], MAX_RETRY_ATTEMPTS)

    def test_schedule_feature_flag_update_variants(self) -> None:
        """Test that scheduled update_variants operation correctly updates variants and payloads"""
        # Create initial variants
        initial_variants = [
            {
                "key": "control",
                "name": "Control",
                "rollout_percentage": 50,
            },
            {
                "key": "test",
                "name": "Test",
                "rollout_percentage": 50,
            },
        ]

        # Create initial payloads (key-based format for serializer validation)
        initial_payloads = {
            "control": {"message": "control message"},
            "test": {"message": "test message"},
        }

        feature_flag = FeatureFlag.objects.create(
            name="Variant Flag",
            key="variant-flag",
            active=True,
            filters={
                "groups": [],
                "multivariate": {"variants": initial_variants},
                "payloads": initial_payloads,
            },
            team=self.team,
            created_by=self.user,
        )

        # Create new variants configuration
        new_variants = [
            {
                "key": "control",
                "name": "Control Updated",
                "rollout_percentage": 30,
            },
            {
                "key": "test",
                "name": "Test Updated",
                "rollout_percentage": 40,
            },
            {
                "key": "new-variant",
                "name": "New Variant",
                "rollout_percentage": 30,
            },
        ]

        # Create new payloads (key-based format for serializer validation)
        new_payloads = {
            "control": {"message": "updated control message"},
            "test": {"message": "updated test message"},
            "new-variant": {"message": "new variant message"},
        }

        payload = {
            "operation": "update_variants",
            "value": {
                "variants": new_variants,
                "payloads": new_payloads,
            },
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        process_scheduled_changes()

        # Verify the flag was updated
        updated_flag = FeatureFlag.objects.get(key="variant-flag")

        # Check that variants were updated
        self.assertEqual(len(updated_flag.filters["multivariate"]["variants"]), 3)
        self.assertEqual(updated_flag.filters["multivariate"]["variants"], new_variants)

        # Check that payloads were updated
        self.assertEqual(updated_flag.filters["payloads"], new_payloads)

        # Verify other filter properties were preserved
        self.assertEqual(updated_flag.filters["groups"], [])
        self.assertTrue(updated_flag.active)

    def test_schedule_feature_flag_update_variants_preserve_other_filters(self) -> None:
        """Test that update_variants preserves existing release conditions and other filter properties"""
        # Create initial setup with release conditions
        initial_variants = [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "name": "Test", "rollout_percentage": 50},
        ]

        existing_release_condition = {
            "variant": None,
            "properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}],
            "rollout_percentage": 75,
        }

        feature_flag = FeatureFlag.objects.create(
            name="Complex Variant Flag",
            key="complex-variant-flag",
            active=True,
            filters={
                "groups": [existing_release_condition],
                "multivariate": {"variants": initial_variants},
                "payloads": {"control": {"msg": "control"}, "test": {"msg": "test"}},
            },
            team=self.team,
            created_by=self.user,
        )

        # Update only variants, not release conditions
        new_variants = [
            {"key": "control", "name": "Control V2", "rollout_percentage": 60},
            {"key": "test", "name": "Test V2", "rollout_percentage": 40},
        ]

        new_payloads = {
            "control": {"msg": "control v2"},
            "test": {"msg": "test v2"},
        }

        payload = {
            "operation": "update_variants",
            "value": {
                "variants": new_variants,
                "payloads": new_payloads,
            },
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        process_scheduled_changes()

        # Verify the flag was updated
        updated_flag = FeatureFlag.objects.get(key="complex-variant-flag")

        # Check that variants were updated
        self.assertEqual(updated_flag.filters["multivariate"]["variants"], new_variants)
        self.assertEqual(updated_flag.filters["payloads"], new_payloads)

        # Check that existing release conditions were preserved
        self.assertEqual(len(updated_flag.filters["groups"]), 1)
        self.assertEqual(updated_flag.filters["groups"][0], existing_release_condition)

    def test_schedule_feature_flag_update_variants_empty_variants_with_payloads(self) -> None:
        """Test that update_variants works correctly when clearing variants but having old payloads"""
        # Create initial setup with variants and payloads
        initial_variants = [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "name": "Test", "rollout_percentage": 50},
        ]

        feature_flag = FeatureFlag.objects.create(
            name="Test Variant Flag",
            key="test-variant-flag",
            active=True,
            filters={
                "groups": [],
                "multivariate": {"variants": initial_variants},
                "payloads": {"control": {"msg": "control"}, "test": {"msg": "test"}},
            },
            team=self.team,
            created_by=self.user,
        )

        # Clear variants and payloads (this was causing the validation error)
        payload = {
            "operation": "update_variants",
            "value": {
                "variants": [],  # Empty variants
                "payloads": {},  # Empty payloads
            },
        }

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        process_scheduled_changes()

        # Verify the flag was updated correctly
        updated_flag = FeatureFlag.objects.get(key="test-variant-flag")

        # Check that variants were cleared
        self.assertEqual(updated_flag.filters["multivariate"]["variants"], [])
        self.assertEqual(updated_flag.filters["payloads"], {})

    def test_schedule_feature_flag_update_variants_with_mismatched_payload_keys_fails(self) -> None:
        """Test that update_variants fails validation when payload keys don't match variant keys"""
        initial_variants = [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "name": "Test", "rollout_percentage": 50},
        ]

        feature_flag = FeatureFlag.objects.create(
            name="Mismatched Payload Flag",
            key="mismatched-payload-flag",
            active=True,
            filters={
                "groups": [],
                "multivariate": {"variants": initial_variants},
                "payloads": {"control": {"msg": "control"}, "test": {"msg": "test"}},
            },
            team=self.team,
            created_by=self.user,
        )

        new_variants = [
            {"key": "orange", "name": "a", "rollout_percentage": 40},
            {"key": "apples", "name": "b", "rollout_percentage": 25},
            {"key": "test", "name": "c", "rollout_percentage": 5},
            {"key": "variant", "name": "d", "rollout_percentage": 30},
        ]

        mismatched_payloads = {
            "0": '{"value": 1}',
            "1": '{"value": 2}',
            "2": '{"value": 35}',
            "3": '{"value": 5}',
        }

        payload = {
            "operation": "update_variants",
            "value": {
                "variants": new_variants,
                "payloads": mismatched_payloads,
            },
        }

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=(datetime.now(UTC) - timedelta(seconds=30)),
            created_by=self.user,
        )

        process_scheduled_changes()

        updated_flag = FeatureFlag.objects.get(key="mismatched-payload-flag")

        self.assertEqual(len(updated_flag.filters["multivariate"]["variants"]), 2)
        self.assertEqual(updated_flag.filters["multivariate"]["variants"], initial_variants)

        updated_scheduled_change = ScheduledChange.objects.get(id=scheduled_change.id)
        self.assertIsNotNone(updated_scheduled_change.failure_reason)
        self.assertEqual(updated_scheduled_change.failure_count, 1)
