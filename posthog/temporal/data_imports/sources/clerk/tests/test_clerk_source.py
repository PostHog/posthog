import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.clerk.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.clerk.source import ClerkSource
from posthog.temporal.data_imports.sources.generated_configs import ClerkSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestClerkSource:
    def setup_method(self):
        self.source = ClerkSource()
        self.team_id = 123
        self.config = ClerkSourceConfig(secret_key="sk_live_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CLERK

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Clerk"
        assert config.label == "Clerk"
        assert config.iconPath == "/static/services/clerk.png"
        assert len(config.fields) == 1

        secret_key_field = config.fields[0]
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.name == "secret_key"
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.required is True

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()

        assert "401 Client Error: Unauthorized for url: https://api.clerk.com" in errors
        assert "403 Client Error: Forbidden for url: https://api.clerk.com" in errors

        real_error = "403 Client Error: Forbidden for url: https://api.clerk.com/v1/organizations?limit=100"
        assert any(key in real_error for key in errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])

        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize(
        ("return_value", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid Clerk credentials"), False, "Invalid Clerk credentials"),
        ],
    )
    @mock.patch("posthog.temporal.data_imports.sources.clerk.source.validate_clerk_credentials")
    def test_validate_credentials(self, mock_validate, return_value, expected_valid, expected_message):
        mock_validate.return_value = return_value

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.secret_key)
