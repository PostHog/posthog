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

        self.assertIn("latest_runs", batch_export_exclusions)
        self.assertIn("last_updated_at", batch_export_exclusions)
        self.assertIn("last_paused_at", batch_export_exclusions)
        self.assertIn("batchexportrun_set", batch_export_exclusions)
        self.assertIn("batchexportbackfill_set", batch_export_exclusions)

    def test_batch_export_scope_in_activity_log_types(self):
        """Test that BatchExport scope is defined in ActivityScope"""
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        # Check that BatchExport is in the literal type
        # We can't directly test literal types, but we can test that the string value works
        self.assertIn("BatchExport", get_args(ActivityScope))

    def test_batch_export_integration_test(self):
        """Integration test to verify the basic setup works"""
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_export = self.create_batch_export(name="Integration Test Export")
            self.assertIsNotNone(batch_export["id"])

            self.update_batch_export(batch_export["id"], {"paused": True, "name": "Updated Export"})
            self.update_batch_export(batch_export["id"], {"interval": "day"})
        finally:
            activity_storage.clear_user()

    def test_batch_export_status_changes(self):
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_export = self.create_batch_export(name="Status Test Export", paused=False)

            # Test pausing/unpausing which should appear as "enabled" field in activity log
            self.update_batch_export(batch_export["id"], {"paused": True})
            self.update_batch_export(batch_export["id"], {"paused": False})
            self.update_batch_export(batch_export["id"], {"model": "persons"})
            self.update_batch_export(
                batch_export["id"], {"schema": [{"alias": "test", "table": "events", "fields": ["event"]}]}
            )

        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_create(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            initial_count = ActivityLog.objects.count()

            batch_export = self.create_batch_export(name="Signal Test Export")

            self.assertEqual(ActivityLog.objects.count(), initial_count + 1)

            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="created", item_id=batch_export["id"]
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None
            self.assertEqual(activity_log.user, self.user)
            self.assertEqual(activity_log.team_id, self.team.id)
            self.assertEqual(activity_log.organization_id, self.team.organization_id)

            assert activity_log.detail is not None
            context = activity_log.detail.get("context")
            self.assertIsNotNone(context)
            self.assertEqual(context["name"], "Signal Test Export")
            self.assertEqual(context["destination_type"], "HTTP")
            self.assertEqual(context["interval"], "hour")
        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_update(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_export = self.create_batch_export(name="Update Test Export")
            initial_count = ActivityLog.objects.count()

            self.update_batch_export(batch_export["id"], {"name": "Updated Test Export", "interval": "day"})

            self.assertEqual(ActivityLog.objects.count(), initial_count + 1)

            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="updated", item_id=batch_export["id"]
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None
            self.assertEqual(activity_log.user, self.user)

            assert activity_log.detail is not None
            changes = activity_log.detail.get("changes", [])
            self.assertTrue(len(changes) > 0)
        finally:
            activity_storage.clear_user()

    def test_batch_export_signal_handler_delete(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_export = self.create_batch_export(name="Delete Test Export")
            batch_export_id = batch_export["id"]
            initial_count = ActivityLog.objects.count()

            self.delete_batch_export(batch_export_id)

            self.assertEqual(ActivityLog.objects.count(), initial_count + 1)

            activity_log = ActivityLog.objects.filter(
                scope="BatchExport", activity="updated", item_id=batch_export_id
            ).first()

            self.assertIsNotNone(activity_log)
            assert activity_log is not None
            self.assertEqual(activity_log.user, self.user)

            assert activity_log.detail is not None
            changes = activity_log.detail.get("changes", [])
            deleted_change = next((change for change in changes if change["field"] == "deleted"), None)
            self.assertIsNotNone(deleted_change)

        finally:
            activity_storage.clear_user()
