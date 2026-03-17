from typing import Any, cast

from unittest.mock import patch

from posthog.temporal.data_imports.sources.generated_configs import TypeformSourceConfig
from posthog.temporal.data_imports.sources.typeform.source import TypeformSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestTypeformSource:
    def test_source_type(self) -> None:
        source = TypeformSource()
        assert source.source_type == ExternalDataSourceType.TYPEFORM

    def test_get_source_config_fields(self) -> None:
        source = TypeformSource()
        source_config = source.get_source_config

        assert source_config.name == "Typeform"
        assert source_config.betaSource is True
        field_names = [cast(Any, field).name for field in source_config.fields]
        assert "auth_token" in field_names
        assert "api_base_url" in field_names

    def test_get_schemas(self) -> None:
        source = TypeformSource()
        config = TypeformSourceConfig(auth_token="token", api_base_url="https://api.typeform.com")
        schemas = source.get_schemas(config, team_id=1)

        assert len(schemas) == 2
        schema_by_name = {schema.name: schema for schema in schemas}
        assert schema_by_name["forms"].supports_incremental is True
        assert schema_by_name["responses"].supports_incremental is True
        assert schema_by_name["forms"].incremental_fields[0]["field"] == "last_updated_at"
        assert schema_by_name["responses"].incremental_fields[0]["field"] == "submitted_at"

    @patch("posthog.temporal.data_imports.sources.typeform.source.validate_typeform_credentials")
    def test_validate_credentials_delegates(self, mock_validate) -> None:
        source = TypeformSource()
        config = TypeformSourceConfig(auth_token="token", api_base_url="https://api.typeform.com")
        mock_validate.return_value = (True, None)

        result = source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            auth_token="token",
            api_base_url="https://api.typeform.com",
        )

    @patch("posthog.temporal.data_imports.sources.typeform.source.validate_typeform_credentials")
    def test_validate_credentials_rejects_unknown_api_base_url(self, mock_validate) -> None:
        source = TypeformSource()
        config = TypeformSourceConfig(auth_token="token", api_base_url=cast(Any, "https://unknown.typeform.com"))

        result = source.validate_credentials(config, team_id=1)

        assert result == (
            False,
            "API base URL must be one of https://api.typeform.com, https://api.eu.typeform.com, or https://api.typeform.eu.",
        )
        mock_validate.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.typeform.source.validate_typeform_credentials")
    def test_validate_credentials_defaults_missing_api_base_url(self, mock_validate) -> None:
        source = TypeformSource()
        config = TypeformSourceConfig(auth_token="token")
        mock_validate.return_value = (True, None)

        result = source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            auth_token="token",
            api_base_url="https://api.typeform.com",
        )

    def test_get_non_retryable_errors(self) -> None:
        source = TypeformSource()
        errors = source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    @patch("posthog.temporal.data_imports.sources.typeform.source.typeform_source")
    def test_source_for_pipeline_argument_plumbing(self, mock_typeform_source) -> None:
        source = TypeformSource()
        config = TypeformSourceConfig(auth_token="token", api_base_url="https://api.typeform.com")
        inputs = cast(Any, type("Inputs", (), {})())
        inputs.schema_name = "forms"
        inputs.team_id = 2
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "last_updated_at"

        source.source_for_pipeline(config, inputs)

        mock_typeform_source.assert_called_once_with(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            endpoint="forms",
            team_id=2,
            job_id="job-123",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="last_updated_at",
        )
