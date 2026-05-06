from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.generated_configs import PgAnalyzeSourceConfig
from posthog.temporal.data_imports.sources.pganalyze.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.pganalyze.source import PgAnalyzeSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestPgAnalyzeSource:
    def setup_method(self):
        self.source = PgAnalyzeSource()
        self.team_id = 123
        self.config = PgAnalyzeSourceConfig(
            api_key="pganalyze_test_token",
            organization_slug="acme",
            api_url=None,
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PGANALYZE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "PgAnalyze"
        assert config.label == "pganalyze"
        assert config.iconPath == "/static/services/pganalyze.svg"
        assert len(config.fields) == 3

        names = {field.name for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert {"api_key", "organization_slug", "api_url"} == names

        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        api_url_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_url")
        assert api_url_field.required is False

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])

        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_servers_schema_does_not_support_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["servers"])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is False

    def test_issues_schema_supports_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is True

    @mock.patch("posthog.temporal.data_imports.sources.pganalyze.source.validate_pganalyze_credentials")
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(
            api_key=self.config.api_key,
            organization_slug=self.config.organization_slug,
            api_url=self.config.api_url,
        )

    @mock.patch("posthog.temporal.data_imports.sources.pganalyze.source.validate_pganalyze_credentials")
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = (False, "Invalid pganalyze API token")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid pganalyze API token"

    @mock.patch("posthog.temporal.data_imports.sources.pganalyze.source.pganalyze_source")
    def test_source_for_pipeline_non_incremental(self, mock_pganalyze_source):
        mock_pganalyze_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, inputs)

        mock_pganalyze_source.assert_called_once_with(
            api_key=self.config.api_key,
            api_url=self.config.api_url,
            organization_slug=self.config.organization_slug,
            endpoint_name="issues",
            logger=inputs.logger,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.pganalyze.source.pganalyze_source")
    def test_source_for_pipeline_incremental_passes_last_value(self, mock_pganalyze_source):
        mock_pganalyze_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-04-20T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_pganalyze_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-04-20T00:00:00+00:00"
