from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.generated_configs import PlainSourceConfig
from posthog.temporal.data_imports.sources.plain.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.plain.source import PlainSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestPlainSource:
    def setup_method(self):
        self.source = PlainSource()
        self.team_id = 123
        self.config = PlainSourceConfig(api_key="plainApiKey_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PLAIN

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Plain"
        assert config.label == "Plain"
        assert config.releaseStatus == "beta"
        assert config.featureFlag == "dwh_plain"
        assert config.iconPath == "/static/services/plain.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])

        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch("posthog.temporal.data_imports.sources.plain.source.validate_plain_credentials")
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch("posthog.temporal.data_imports.sources.plain.source.validate_plain_credentials")
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = (False, "Invalid Plain credentials")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Plain credentials"

    @mock.patch("posthog.temporal.data_imports.sources.plain.source.plain_source")
    def test_source_for_pipeline_non_incremental(self, mock_plain_source):
        mock_plain_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_plain_source.assert_called_once_with(
            api_key=self.config.api_key,
            endpoint_name="customers",
            logger=inputs.logger,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.plain.source.plain_source")
    def test_source_for_pipeline_incremental(self, mock_plain_source):
        mock_plain_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "threads"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_plain_source.assert_called_once_with(
            api_key=self.config.api_key,
            endpoint_name="threads",
            logger=inputs.logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
