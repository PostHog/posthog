from typing import get_args

from posthog.models.activity_logging.activity_log import ActivityScope, field_exclusions
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.test.activity_log_utils import ActivityLogTestHelper
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema


class TestExternalDataSchemaActivityLogging(ActivityLogTestHelper):
    def test_external_data_schema_model_has_activity_mixin(self):
        self.assertTrue(issubclass(ExternalDataSchema, ModelActivityMixin))

    def test_external_data_schema_field_exclusions_configured(self):
        external_data_schema_exclusions = field_exclusions.get("ExternalDataSchema", [])

        self.assertIn("sync_type_config", external_data_schema_exclusions)
        self.assertIn("latest_error", external_data_schema_exclusions)
        self.assertIn("last_synced_at", external_data_schema_exclusions)
        self.assertIn("status", external_data_schema_exclusions)
        self.assertEqual(len(external_data_schema_exclusions), 4)

    def test_external_data_schema_scope_in_activity_log_types(self):
        self.assertIn("ExternalDataSchema", get_args(ActivityScope))

    def test_external_data_schema_creation_activity_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        # Verify that no creation logs are created
        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 0)

    def test_external_data_schema_update_activity_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

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

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None
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
        assert deleted_change is not None
        self.assertEqual(deleted_change["after"], True)

    def test_external_data_schema_relationship_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 0)

        self.update_external_data_schema(str(schema.id), {"should_sync": False})

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")

        context = log_entry.detail.get("context")
        self.assertIsNotNone(context)
        self.assertEqual(context.get("source_id"), str(source_obj.id))
        self.assertEqual(context.get("source_type"), "Stripe")
