from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


class TestExternalDataSourceActivityLogging(ActivityLogTestHelper):
    def test_external_data_source_model_has_activity_mixin(self):
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        self.assertTrue(issubclass(ExternalDataSource, ModelActivityMixin))

    def test_external_data_source_field_exclusions_configured(self):
        from posthog.models.activity_logging.activity_log import field_exclusions

        external_data_source_exclusions = field_exclusions.get("ExternalDataSource", [])

        self.assertIn("connection_id", external_data_source_exclusions)
        self.assertIn("destination_id", external_data_source_exclusions)
        self.assertIn("are_tables_created", external_data_source_exclusions)

    def test_external_data_source_scope_in_activity_log_types(self):
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        self.assertIn("ExternalDataSource", get_args(ActivityScope))

    def test_external_data_source_creation_activity_logging(self):
        external_data_source = self.create_external_data_source()

        activity_logs = self.get_activity_logs_for_item("ExternalDataSource", external_data_source["id"])
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "created")
        self.assertEqual(log_entry.scope, "ExternalDataSource")
        self.assertEqual(log_entry.item_id, external_data_source["id"])

        detail_changes = log_entry.detail.get("changes", [])
        field_names = [change.get("field") for change in detail_changes if change.get("field")]

        self.assertNotIn("job_inputs", field_names)
        self.assertNotIn("connection_id", field_names)
        self.assertNotIn("destination_id", field_names)
        self.assertNotIn("are_tables_created", field_names)

    def test_external_data_source_deletion_activity_logging(self):
        external_data_source = self.create_external_data_source()
        external_data_source_id = external_data_source["id"]

        self.clear_activity_logs()

        self.delete_external_data_source(external_data_source_id)

        activity_logs = self.get_activity_logs_for_item("ExternalDataSource", external_data_source_id)
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")
        self.assertEqual(log_entry.scope, "ExternalDataSource")

        # Check that deletion is tracked via deleted field change
        detail_changes = log_entry.detail.get("changes", [])
        deleted_change = next((change for change in detail_changes if change.get("field") == "deleted"), None)
        self.assertIsNotNone(deleted_change)
        assert deleted_change is not None
        self.assertEqual(deleted_change["after"], True)
