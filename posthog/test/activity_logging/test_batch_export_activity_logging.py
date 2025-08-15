from posthog.batch_exports.models import BatchExport, BatchExportDestination
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestBatchExportActivityLogging(ActivityLogTestHelper):
    def create_test_destination(self):
        """Helper to create a test destination for batch exports."""
        return BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.HTTP, config={"url": "https://example.com"}
        )

    def test_batch_export_model_has_activity_mixin(self):
        """Test that BatchExport has ModelActivityMixin and proper scope"""
        # Verify that BatchExport inherits from ModelActivityMixin
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        self.assertTrue(issubclass(BatchExport, ModelActivityMixin))

        # Test that the model can be created
        destination = self.create_test_destination()
        batch_export = BatchExport.objects.create(
            team=self.team, name="Test Export", destination=destination, interval="hour"
        )

        self.assertIsNotNone(batch_export)
        self.assertEqual(batch_export.team, self.team)
        self.assertEqual(batch_export.name, "Test Export")

    def test_batch_export_field_exclusions_configured(self):
        """Test that field exclusions are properly configured"""
        from posthog.models.activity_logging.activity_log import field_exclusions

        batch_export_exclusions = field_exclusions.get("BatchExport", [])

        # Verify reverse relation fields are excluded
        self.assertIn("latest_runs", batch_export_exclusions)
        self.assertIn("batchexportrun_set", batch_export_exclusions)
        self.assertIn("batchexportbackfill_set", batch_export_exclusions)

    def test_batch_export_scope_in_activity_log_types(self):
        """Test that BatchExport scope is defined in ActivityScope"""
        from posthog.models.activity_logging.activity_log import ActivityScope
        from typing import get_args

        # Check that BatchExport is in the literal type
        # We can't directly test literal types, but we can test that the string value works
        self.assertIn("BatchExport", get_args(ActivityScope))

    def test_batch_export_integration_test(self):
        """Integration test to verify the basic setup works"""
        # This is a minimal test to ensure no errors in the setup
        from posthog.models.activity_logging.utils import activity_storage

        # Set user context
        activity_storage.set_user(self.user)

        try:
            # Create a batch export
            destination = self.create_test_destination()
            batch_export = BatchExport.objects.create(
                team=self.team, name="Integration Test Export", destination=destination, interval="hour", paused=False
            )

            # Test basic model functionality
            self.assertIsNotNone(batch_export.id)
            self.assertEqual(batch_export.team, self.team)
            self.assertEqual(batch_export.name, "Integration Test Export")

            # Update the batch export to test update signals
            batch_export.paused = True
            batch_export.name = "Updated Integration Test Export"
            batch_export.save()

            # Test that we can update the interval
            batch_export.interval = "day"
            batch_export.save()

            # The test passes if no exceptions are raised during save operations

        finally:
            activity_storage.clear_user()

    def test_batch_export_status_changes(self):
        """Test various status changes on batch exports"""
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            destination = self.create_test_destination()
            batch_export = BatchExport.objects.create(
                team=self.team, name="Status Test Export", destination=destination, interval="hour", paused=False
            )

            # Test pause
            batch_export.paused = True
            batch_export.save()

            # Test resume
            batch_export.paused = False
            batch_export.save()

            # Test model change
            batch_export.model = "persons"
            batch_export.save()

            # Test schema change
            batch_export.schema = [{"alias": "test", "table": "events", "fields": ["event"]}]
            batch_export.save()

            # All operations should complete without errors

        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_create(self):
        """Test that the signal handler works for batch export creation"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            initial_count = ActivityLog.objects.count()

            # Create a batch export
            destination = self.create_test_destination()
            batch_export = BatchExport.objects.create(
                team=self.team, name="Signal Test Export", destination=destination, interval="hour"
            )

            # Check that activity log was created
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="created", item_id=str(batch_export.id)
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None  # For mypy
            self.assertEqual(activity_log.user, self.user)
            self.assertEqual(activity_log.team_id, self.team.id)
            self.assertEqual(activity_log.organization_id, self.team.organization_id)

            # Check that context is populated
            self.assertIsNotNone(activity_log.detail)
            assert activity_log.detail is not None  # For mypy
            context = activity_log.detail.get("context")
            self.assertIsNotNone(context)
            self.assertEqual(context["name"], "Signal Test Export")
            self.assertEqual(context["destination_type"], "HTTP")
            self.assertEqual(context["interval"], "hour")

        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_update(self):
        """Test that the signal handler works for batch export updates"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            # Create a batch export first
            destination = self.create_test_destination()
            batch_export = BatchExport.objects.create(
                team=self.team, name="Update Test Export", destination=destination, interval="hour"
            )

            initial_count = ActivityLog.objects.count()

            # Update the batch export
            batch_export.name = "Updated Test Export"
            batch_export.interval = "day"
            batch_export.save()

            # Check that activity log was created for the update
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the update activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="updated", item_id=str(batch_export.id)
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None  # For mypy
            self.assertEqual(activity_log.user, self.user)

            # Check that changes are recorded
            assert activity_log.detail is not None  # For mypy
            changes = activity_log.detail.get("changes", [])
            self.assertTrue(len(changes) > 0)

        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_delete(self):
        """Test that the signal handler works for batch export deletion"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            # Create a batch export first
            destination = self.create_test_destination()
            batch_export = BatchExport.objects.create(
                team=self.team, name="Delete Test Export", destination=destination, interval="hour"
            )
            batch_export_id = batch_export.id

            # Get initial count AFTER creation (since creation also generates an activity log)
            initial_count = ActivityLog.objects.count()

            # Delete the batch export
            batch_export.delete()

            # Check that activity log was created for the deletion
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the delete activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="deleted", item_id=str(batch_export_id)
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None  # For mypy
            self.assertEqual(activity_log.user, self.user)

        finally:
            activity_storage.clear_user()
