from posthog.models.batch_imports import BatchImport
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestBatchImportActivityLogging(ActivityLogTestHelper):
    def test_batch_import_model_has_activity_mixin(self):
        """Test that BatchImport has ModelActivityMixin and proper scope"""
        # Verify that BatchImport inherits from ModelActivityMixin
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        assert issubclass(BatchImport, ModelActivityMixin)

        # Test that the model can be created
        batch_import = BatchImport.objects.create(
            team=self.team, created_by_id=self.user.id, import_config={"source": {"type": "test"}}, secrets="{}"
        )

        assert batch_import is not None
        assert batch_import.team == self.team

    def test_batch_import_field_exclusions_configured(self):
        """Test that field exclusions are properly configured"""
        from posthog.models.activity_logging.activity_log import field_exclusions

        batch_import_exclusions = field_exclusions.get("BatchImport", [])

        # Verify sensitive fields are excluded
        assert "secrets" in batch_import_exclusions
        assert "lease_id" in batch_import_exclusions
        assert "state" in batch_import_exclusions
        assert "status_message" in batch_import_exclusions
        assert "backoff_attempt" in batch_import_exclusions
        assert "backoff_until" in batch_import_exclusions

    def test_batch_import_scope_in_activity_log_types(self):
        """Test that BatchImport scope is defined in ActivityScope"""
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        # Check that BatchImport is in the literal type
        # We can't directly test literal types, but we can test that the string value works
        assert "BatchImport" in get_args(ActivityScope)

    def test_batch_import_masked_fields_configured(self):
        """Test that masked fields are properly configured"""
        from posthog.models.activity_logging.activity_log import field_with_masked_contents

        batch_import_masked = field_with_masked_contents.get("BatchImport", [])

        # Verify import_config is masked
        assert "import_config" in batch_import_masked

    def test_batch_import_integration_test(self):
        """Integration test to verify the basic setup works"""
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_import = self.create_batch_import()
            assert batch_import["id"] is not None

            self.update_batch_import(batch_import["id"], {"status": "completed"})
        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_create(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            initial_count = ActivityLog.objects.count()

            batch_import = self.create_batch_import(
                import_config={"source": {"type": "s3"}, "data_format": {"content": {"type": "mixpanel"}}}
            )

            assert ActivityLog.objects.count() == initial_count + 1

            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="created", item_id=batch_import["id"]
            ).first()

            assert activity_log is not None
            assert activity_log is not None
            assert activity_log.user == self.user
            assert activity_log.team_id == self.team.id
            assert activity_log.organization_id == self.team.organization_id

            assert activity_log.detail is not None
            context = activity_log.detail.get("context")
            assert context is not None
            assert context["source_type"] == "s3"
            assert context["content_type"] == "mixpanel"
            assert context["created_by_user_id"] == str(self.user.id)
        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_update(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_import = self.create_batch_import()
            initial_count = ActivityLog.objects.count()

            self.update_batch_import(batch_import["id"], {"status": "completed"})

            assert ActivityLog.objects.count() == initial_count + 1

            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="updated", item_id=batch_import["id"]
            ).first()

            assert activity_log is not None
            assert activity_log is not None
            assert activity_log.user == self.user

            assert activity_log.detail is not None
            changes = activity_log.detail.get("changes", [])
            assert len(changes) > 0
        finally:
            activity_storage.clear_user()

    def test_batch_import_signal_handler_delete(self):
        from posthog.models.activity_logging.activity_log import ActivityLog
        from posthog.models.activity_logging.utils import activity_storage

        activity_storage.set_user(self.user)
        try:
            batch_import = self.create_batch_import()
            batch_import_id = batch_import["id"]
            initial_count = ActivityLog.objects.count()

            self.delete_batch_import(batch_import_id)

            assert ActivityLog.objects.count() == initial_count + 1

            activity_log = ActivityLog.objects.filter(
                scope="BatchImport", activity="deleted", item_id=batch_import_id
            ).first()

            assert activity_log is not None
            assert activity_log is not None
            assert activity_log.user == self.user
        finally:
            activity_storage.clear_user()
