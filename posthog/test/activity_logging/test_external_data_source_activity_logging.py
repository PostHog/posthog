from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


class TestExternalDataSourceActivityLogging(ActivityLogTestHelper):
    def test_external_data_source_model_has_activity_mixin(self):
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        assert issubclass(ExternalDataSource, ModelActivityMixin)

    def test_external_data_source_field_exclusions_configured(self):
        from posthog.models.activity_logging.activity_log import field_exclusions

        external_data_source_exclusions = field_exclusions.get("ExternalDataSource", [])

        assert "connection_id" in external_data_source_exclusions
        assert "destination_id" in external_data_source_exclusions
        assert "are_tables_created" in external_data_source_exclusions

    def test_external_data_source_scope_in_activity_log_types(self):
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        assert "ExternalDataSource" in get_args(ActivityScope)

    def test_external_data_source_creation_activity_logging(self):
        external_data_source = self.create_external_data_source()

        activity_logs = self.get_activity_logs_for_item("ExternalDataSource", external_data_source["id"])
        assert len(activity_logs) == 1

        log_entry = activity_logs[0]
        assert log_entry.activity == "created"
        assert log_entry.scope == "ExternalDataSource"
        assert log_entry.item_id == external_data_source["id"]

        detail_changes = log_entry.detail.get("changes", [])
        field_names = [change.get("field") for change in detail_changes if change.get("field")]

        assert "job_inputs" not in field_names
        assert "connection_id" not in field_names
        assert "destination_id" not in field_names
        assert "are_tables_created" not in field_names

    def test_external_data_source_deletion_activity_logging(self):
        external_data_source = self.create_external_data_source()
        external_data_source_id = external_data_source["id"]

        self.clear_activity_logs()

        self.delete_external_data_source(external_data_source_id)

        activity_logs = self.get_activity_logs_for_item("ExternalDataSource", external_data_source_id)
        assert len(activity_logs) == 1

        log_entry = activity_logs[0]
        assert log_entry.activity == "updated"
        assert log_entry.scope == "ExternalDataSource"

        # Check that deletion is tracked via deleted field change
        detail_changes = log_entry.detail.get("changes", [])
        deleted_change = next((change for change in detail_changes if change.get("field") == "deleted"), None)
        assert deleted_change is not None
        assert deleted_change is not None
        assert deleted_change["after"] == True
