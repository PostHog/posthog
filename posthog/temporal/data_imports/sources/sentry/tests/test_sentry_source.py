from datetime import datetime, timedelta
from uuid import uuid4

from unittest.mock import Mock, patch

import structlog
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.generated_configs import SentrySourceConfig
from posthog.temporal.data_imports.sources.sentry.source import SentrySource

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalFieldType


class TestSentrySource:
    def setup_method(self) -> None:
        self.source = SentrySource()
        self.team_id = 123
        self.job_id = str(uuid4())
        self.config = SentrySourceConfig(
            auth_token="test-token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            max_projects_to_sync=150,
            max_issues_to_fanout=250,
            max_pages_per_parent=6,
            request_timeout_seconds=20,
            max_retries=4,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SENTRY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Sentry"
        assert config.label == "Sentry"
        assert len(config.fields) == 8

        auth_field = config.fields[0]
        assert auth_field.name == "auth_token"
        assert auth_field.required is True

        org_field = config.fields[1]
        assert org_field.name == "organization_slug"
        assert org_field.required is True

        base_url_field = config.fields[2]
        assert base_url_field.name == "api_base_url"
        assert base_url_field.required is False

        max_projects_field = config.fields[3]
        assert max_projects_field.name == "max_projects_to_sync"
        assert max_projects_field.required is False

    def test_get_non_retryable_errors(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "404 Client Error" in errors

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        actual = {schema.name for schema in schemas}

        assert actual == {
            "projects",
            "teams",
            "members",
            "organization_users",
            "releases",
            "environments",
            "monitors",
            "issues",
            "project_issues",
            "project_events",
            "project_users",
            "project_client_keys",
            "project_service_hooks",
            "issue_events",
            "issue_hashes",
            "issue_tag_values",
        }

        projects_schema = next(schema for schema in schemas if schema.name == "projects")
        assert projects_schema.supports_incremental is False
        assert projects_schema.incremental_fields == []

        issues_schema = next(schema for schema in schemas if schema.name == "issues")
        assert issues_schema.supports_incremental is True
        assert len(issues_schema.incremental_fields) == 2

    @parameterized.expand(
        [
            ("valid", True, None),
            ("invalid", False, "Invalid Sentry auth token"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.sentry.source.validate_sentry_credentials")
    def test_validate_credentials(self, _name, is_valid, error, mock_validate) -> None:
        mock_validate.return_value = (is_valid, error)

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (is_valid, error)
        mock_validate.assert_called_once_with(
            auth_token="test-token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
        )

    @patch("posthog.temporal.data_imports.sources.sentry.source.sentry_source")
    def test_source_for_pipeline(self, mock_sentry_source) -> None:
        mock_response = Mock()
        mock_sentry_source.return_value = mock_response
        inputs = SourceInputs(
            schema_name="issues",
            schema_id="issues_schema",
            team_id=self.team_id,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now() - timedelta(days=1),
            db_incremental_field_earliest_value=None,
            incremental_field="lastSeen",
            incremental_field_type=IncrementalFieldType.DateTime,
            job_id=self.job_id,
            logger=structlog.get_logger(),
        )

        result = self.source.source_for_pipeline(self.config, inputs)

        assert result == mock_response
        mock_sentry_source.assert_called_once_with(
            auth_token="test-token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issues",
            team_id=self.team_id,
            job_id=self.job_id,
            should_use_incremental_field=True,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            incremental_field="lastSeen",
            max_projects_to_sync=150,
            max_issues_to_fanout=250,
            max_pages_per_parent=6,
            request_timeout_seconds=20,
            max_retries=4,
        )
