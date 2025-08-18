from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestExternalDataSchemaActivityLogging(ActivityLogTestHelper):
    def test_external_data_schema_model_has_activity_mixin(self):
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        self.assertTrue(issubclass(ExternalDataSchema, ModelActivityMixin))

    def test_external_data_schema_field_exclusions_configured(self):
        from posthog.models.activity_logging.activity_log import field_exclusions

        external_data_schema_exclusions = field_exclusions.get("ExternalDataSchema", [])

        self.assertIn("sync_type_config", external_data_schema_exclusions)
        self.assertIn("latest_error", external_data_schema_exclusions)
        self.assertIn("last_synced_at", external_data_schema_exclusions)
        self.assertIn("table", external_data_schema_exclusions)
        self.assertIn("sync_frequency_interval", external_data_schema_exclusions)

    def test_external_data_schema_scope_in_activity_log_types(self):
        from posthog.models.activity_logging.activity_log import ActivityScope
        from typing import get_args

        self.assertIn("ExternalDataSchema", get_args(ActivityScope))

    def test_external_data_schema_creation_activity_logging(self):
        external_data_source = self.create_external_data_source()

        # Get the created schema from the source
        from posthog.warehouse.models import ExternalDataSource

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "created")
        self.assertEqual(log_entry.scope, "ExternalDataSchema")

        detail_changes = log_entry.detail.get("changes", [])
        field_names = [change.get("field") for change in detail_changes if change.get("field")]

        self.assertNotIn("sync_type_config", field_names)
        self.assertNotIn("latest_error", field_names)
        self.assertNotIn("last_synced_at", field_names)
        self.assertNotIn("table", field_names)
        self.assertNotIn("sync_frequency_interval", field_names)

    def test_external_data_schema_update_activity_logging(self):
        external_data_source = self.create_external_data_source()

        # Get the created schema from the source
        from posthog.warehouse.models import ExternalDataSource

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()

        self.clear_activity_logs()

        self.update_external_data_schema(str(schema.id), {"should_sync": False, "sync_type": "incremental"})

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")
        self.assertEqual(log_entry.scope, "ExternalDataSchema")

    def test_external_data_schema_deletion_activity_logging(self):
        external_data_source = self.create_external_data_source()

        # Get the created schema from the source
        from posthog.warehouse.models import ExternalDataSource

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        schema_id = str(schema.id)

        self.clear_activity_logs()

        self.delete_external_data_schema(schema_id)

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", schema_id)
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")
        self.assertEqual(log_entry.scope, "ExternalDataSchema")

        # Check that deletion is tracked via deleted field change
        detail_changes = log_entry.detail.get("changes", [])
        deleted_change = next((change for change in detail_changes if change.get("field") == "deleted"), None)
        self.assertIsNotNone(deleted_change)
        self.assertEqual(deleted_change["after"], True)

    def test_external_data_schema_relationship_logging(self):
        external_data_source = self.create_external_data_source()

        # Get the created schema from the source
        from posthog.warehouse.models import ExternalDataSource

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        detail_changes = log_entry.detail.get("changes", [])
        source_changes = [change for change in detail_changes if change.get("field") == "source"]

        if source_changes:
            source_change = source_changes[0]
            self.assertEqual(source_change.get("after"), external_data_source["id"])
