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
        assert config.releaseStatus == "beta"
        assert config.iconPath == "/static/services/clerk.png"
        assert len(config.fields) == 1

        secret_key_field = config.fields[0]
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.name == "secret_key"
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.required is True

    def test_non_retryable_errors_includes_clerk_401(self):
        errors = self.source.get_non_retryable_errors()

        assert "401 Client Error: Unauthorized for url: https://api.clerk.com" in errors
        assert "403 Client Error: Forbidden for url: https://api.clerk.com" in errors

    def test_non_retryable_errors_matches_observed_error_message(self):
        # Matches the full error string seen in production for the `users` endpoint.
        observed_error = "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users?limit=100"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_other_vendors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()

        for other in (
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.attio.com/v2/objects/users",
        ):
            assert not any(key in other for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch("posthog.temporal.data_imports.sources.clerk.source.validate_clerk_credentials")
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.secret_key)

    @mock.patch("posthog.temporal.data_imports.sources.clerk.source.validate_clerk_credentials")
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = (False, "Invalid Clerk credentials")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Clerk credentials"
