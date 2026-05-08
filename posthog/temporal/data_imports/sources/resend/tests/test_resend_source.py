from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import ResendSourceConfig
from posthog.temporal.data_imports.sources.resend.resend import ResendResumeConfig
from posthog.temporal.data_imports.sources.resend.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.resend.source import ResendSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestResendSource:
    def setup_method(self):
        self.source = ResendSource()
        self.team_id = 123
        self.config = ResendSourceConfig(api_key="re_test_key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RESEND

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Resend"
        assert config.label == "Resend"
        assert config.releaseStatus == "alpha"
        assert config.iconPath == "/static/services/resend.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["emails"])

        assert len(schemas) == 1
        assert schemas[0].name == "emails"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch("posthog.temporal.data_imports.sources.resend.source.validate_resend_credentials")
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch("posthog.temporal.data_imports.sources.resend.source.validate_resend_credentials")
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Resend API key"

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ResendResumeConfig

    @mock.patch("posthog.temporal.data_imports.sources.resend.source.resend_source")
    def test_source_for_pipeline(self, mock_resend_source):
        mock_resend_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "audiences"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_resend_source.assert_called_once_with(
            api_key=self.config.api_key,
            endpoint="audiences",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
