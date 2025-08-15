from posthog.models.batch_imports import BatchImport
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestBatchImportActivityLogging(ActivityLogTestHelper):
    def test_batch_import_model_has_activity_mixin(self):
        """Test that BatchImport has ModelActivityMixin and proper scope"""
        # Verify that BatchImport inherits from ModelActivityMixin
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        self.assertTrue(issubclass(BatchImport, ModelActivityMixin))

        # Test that the model can be created
        batch_import = BatchImport.objects.create(
            team=self.team, created_by_id=self.user.id, import_config={"source": {"type": "test"}}, secrets="{}"
        )

        self.assertIsNotNone(batch_import)
        self.assertEqual(batch_import.team, self.team)

    def test_batch_import_field_exclusions_configured(self):
        """Test that field exclusions are properly configured"""
        from posthog.models.activity_logging.activity_log import field_exclusions

        batch_import_exclusions = field_exclusions.get("BatchImport", [])

        # Verify sensitive fields are excluded
        self.assertIn("secrets", batch_import_exclusions)
        self.assertIn("lease_id", batch_import_exclusions)
        self.assertIn("state", batch_import_exclusions)
        self.assertIn("status_message", batch_import_exclusions)
        self.assertIn("backoff_attempt", batch_import_exclusions)
        self.assertIn("backoff_until", batch_import_exclusions)

    def test_batch_import_scope_in_activity_log_types(self):
        """Test that BatchImport scope is defined in ActivityScope"""
        from posthog.models.activity_logging.activity_log import ActivityScope

        # Check that BatchImport is in the literal type
        # We can't directly test literal types, but we can test that the string value works
        self.assertIn("BatchImport", str(ActivityScope.__args__))

    def test_batch_import_masked_fields_configured(self):
        """Test that masked fields are properly configured"""
        from posthog.models.activity_logging.activity_log import field_with_masked_contents

        batch_import_masked = field_with_masked_contents.get("BatchImport", [])

        # Verify import_config is masked
        self.assertIn("import_config", batch_import_masked)

    def test_batch_import_integration_test(self):
        """Integration test to verify the basic setup works"""
        # This is a minimal test to ensure no errors in the setup
        from posthog.models.activity_logging.utils import activity_storage

        # Set user context
        activity_storage.set_user(self.user)

        try:
            # Create a batch import
            batch_import = BatchImport.objects.create(
                team=self.team, created_by_id=self.user.id, import_config={"source": {"type": "test"}}, secrets="{}"
            )

            # Test basic model functionality
            self.assertIsNotNone(batch_import.id)
            self.assertEqual(batch_import.team, self.team)

            # Update the batch import to test update signals
            batch_import.status = BatchImport.Status.COMPLETED
            batch_import.save()

            # The test passes if no exceptions are raised during save operations

        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_create(self):
        """Test that the signal handler works for batch import creation"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            initial_count = ActivityLog.objects.count()

            # Create a batch import
            batch_import = BatchImport.objects.create(
                team=self.team,
                created_by_id=self.user.id,
                import_config={"source": {"type": "s3"}, "data_format": {"content": {"type": "mixpanel"}}},
                secrets="{}",
            )

            # Check that activity log was created
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="created", item_id=str(batch_import.id)
            ).first()

            self.assertIsNotNone(activity_log)
            self.assertEqual(activity_log.user, self.user)
            self.assertEqual(activity_log.team_id, self.team.id)
            self.assertEqual(activity_log.organization_id, self.team.organization_id)

            # Check that context is populated
            self.assertIsNotNone(activity_log.detail)
            context = activity_log.detail.get("context")
            self.assertIsNotNone(context)
            self.assertEqual(context["source_type"], "s3")
            self.assertEqual(context["content_type"], "mixpanel")
            self.assertEqual(context["created_by_user_id"], str(self.user.id))

        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_update(self):
        """Test that the signal handler works for batch import updates"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            # Create a batch import first
            batch_import = BatchImport.objects.create(
                team=self.team, created_by_id=self.user.id, import_config={"source": {"type": "test"}}, secrets="{}"
            )

            initial_count = ActivityLog.objects.count()

            # Update the batch import
            batch_import.status = BatchImport.Status.COMPLETED
            batch_import.save()

            # Check that activity log was created for the update
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the update activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="updated", item_id=str(batch_import.id)
            ).first()

            self.assertIsNotNone(activity_log)
            self.assertEqual(activity_log.user, self.user)

            # Check that changes are recorded
            changes = activity_log.detail.get("changes", [])
            self.assertTrue(len(changes) > 0)

        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_delete(self):
        """Test that the signal handler works for batch import deletion"""
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)

        try:
            # Create a batch import first
            batch_import = BatchImport.objects.create(
                team=self.team, created_by_id=self.user.id, import_config={"source": {"type": "test"}}, secrets="{}"
            )
            batch_import_id = batch_import.id

            # Get initial count AFTER creation (since creation also generates an activity log)
            initial_count = ActivityLog.objects.count()

            # Delete the batch import
            batch_import.delete()

            # Check that activity log was created for the deletion
            new_count = ActivityLog.objects.count()
            self.assertEqual(new_count, initial_count + 1)

            # Get the delete activity log entry
            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="deleted", item_id=str(batch_import_id)
            ).first()

            self.assertIsNotNone(activity_log)
            self.assertEqual(activity_log.user, self.user)

        finally:
            activity_storage.clear_user()
