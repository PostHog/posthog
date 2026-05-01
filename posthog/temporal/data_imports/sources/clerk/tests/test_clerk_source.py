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
        assert config.releaseStatus == "beta"
        assert config.iconPath == "/static/services/clerk.png"
        assert len(config.fields) == 1

        secret_key_field = config.fields[0]
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.name == "secret_key"
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.required is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.clerk.com",
            "403 Client Error: Forbidden for url: https://api.clerk.com",
        ],
    )
    def test_non_retryable_errors_includes_clerk_key(self, expected_key):
        errors = self.source.get_non_retryable_errors()

        assert expected_key in errors

    def test_non_retryable_errors_matches_observed_error_message(self):
        # Matches the full error string seen in production for the `users` endpoint.
        observed_error = "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users?limit=100"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.attio.com/v2/objects/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_vendor_error for key in non_retryable_errors)

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

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Clerk credentials"), False, "Invalid Clerk credentials"),
        ],
    )
    @mock.patch("posthog.temporal.data_imports.sources.clerk.source.validate_clerk_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.secret_key)
