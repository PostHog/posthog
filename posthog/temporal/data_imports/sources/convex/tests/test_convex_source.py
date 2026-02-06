from unittest import mock

import requests
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.convex.convex import (
    convex_source,
    document_deltas,
    get_json_schemas,
    list_snapshot,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.convex.source import ConvexSource
from posthog.temporal.data_imports.sources.generated_configs import ConvexSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestConvexSource:
    def setup_method(self):
        self.source = ConvexSource()
        self.team_id = 123
        self.config = ConvexSourceConfig(
            deploy_url="https://test-deployment-123.convex.cloud",
            deploy_key="prod:test_deploy_key_abc123",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CONVEX

    def test_get_source_config_basic(self):
        config = self.source.get_source_config

        assert config.name.value == "Convex"
        assert config.label == "Convex"
        assert config.betaSource is True
        assert config.iconPath == "/static/services/convex.png"
        assert len(config.fields) == 2

    def test_get_source_config_deploy_url_field(self):
        config = self.source.get_source_config
        deploy_url_field = config.fields[0]

        assert isinstance(deploy_url_field, SourceFieldInputConfig)
        assert deploy_url_field.name == "deploy_url"
        assert deploy_url_field.type == SourceFieldInputConfigType.TEXT
        assert deploy_url_field.required is True

    def test_get_source_config_deploy_key_field(self):
        config = self.source.get_source_config
        deploy_key_field = config.fields[1]

        assert isinstance(deploy_key_field, SourceFieldInputConfig)
        assert deploy_key_field.name == "deploy_key"
        assert deploy_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert deploy_key_field.required is True

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.get_json_schemas")
    def test_get_schemas_discovers_tables(self, mock_get_schemas):
        mock_get_schemas.return_value = {
            "users": {"type": "object", "properties": {}},
            "messages": {"type": "object", "properties": {}},
            "channels": {"type": "object", "properties": {}},
        }

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert len(schemas) == 3
        schema_names = {s.name for s in schemas}
        assert schema_names == {"users", "messages", "channels"}

        for schema in schemas:
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert len(schema.incremental_fields) == 1
            assert schema.incremental_fields[0]["field"] == "_ts"

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.get_json_schemas")
    def test_get_schemas_empty_deployment(self, mock_get_schemas):
        mock_get_schemas.return_value = {}

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert len(schemas) == 0

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.validate_convex_credentials")
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_validate.assert_called_once_with(self.config.deploy_url, self.config.deploy_key)

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.validate_convex_credentials")
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = (False, "Invalid deploy key. Check your Convex deploy key and try again.")

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "Invalid deploy key" in error

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.convex_source")
    def test_source_for_pipeline(self, mock_convex_source):
        mock_response = mock.MagicMock()
        mock_convex_source.return_value = mock_response

        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.team_id = self.team_id
        inputs.job_id = "test_job"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        result = self.source.source_for_pipeline(self.config, inputs)

        assert result == mock_response
        mock_convex_source.assert_called_once_with(
            deploy_url=self.config.deploy_url,
            deploy_key=self.config.deploy_key,
            table_name="users",
            team_id=self.team_id,
            job_id="test_job",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.convex.source.convex_source")
    def test_source_for_pipeline_incremental(self, mock_convex_source):
        mock_response = mock.MagicMock()
        mock_convex_source.return_value = mock_response

        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.team_id = self.team_id
        inputs.job_id = "test_job"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1234567890

        result = self.source.source_for_pipeline(self.config, inputs)

        assert result == mock_response
        mock_convex_source.assert_called_once_with(
            deploy_url=self.config.deploy_url,
            deploy_key=self.config.deploy_key,
            table_name="messages",
            team_id=self.team_id,
            job_id="test_job",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1234567890,
        )

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()

        assert "401 Client Error" in errors
        assert "403 Client Error" in errors


class TestConvexAPI:
    DEPLOY_URL = "https://test-deployment-123.convex.cloud"
    DEPLOY_KEY = "prod:test_key"

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_get_json_schemas(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "users": {"type": "object"},
            "messages": {"type": "object"},
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        result = get_json_schemas(self.DEPLOY_URL, self.DEPLOY_KEY)

        assert len(result) == 2
        assert "users" in result
        mock_get.assert_called_once_with(
            f"{self.DEPLOY_URL}/api/json_schemas",
            headers={"Authorization": f"Convex {self.DEPLOY_KEY}", "Content-Type": "application/json"},
            params={"deltaSchema": "true", "format": "json"},
            timeout=30,
        )

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_list_snapshot_single_page(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "values": [{"_id": "1", "name": "Alice", "_ts": 100}],
            "hasMore": False,
            "snapshot": 42,
            "cursor": 1,
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        batches = list(list_snapshot(self.DEPLOY_URL, self.DEPLOY_KEY, "users"))

        assert len(batches) == 1
        assert batches[0] == [{"_id": "1", "name": "Alice", "_ts": 100}]

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_list_snapshot_pagination(self, mock_get):
        page1 = mock.MagicMock()
        page1.json.return_value = {
            "values": [{"_id": "1", "_ts": 100}],
            "hasMore": True,
            "snapshot": 42,
            "cursor": 1,
        }
        page1.raise_for_status = mock.MagicMock()

        page2 = mock.MagicMock()
        page2.json.return_value = {
            "values": [{"_id": "2", "_ts": 200}],
            "hasMore": False,
            "snapshot": 42,
            "cursor": 2,
        }
        page2.raise_for_status = mock.MagicMock()

        mock_get.side_effect = [page1, page2]

        batches = list(list_snapshot(self.DEPLOY_URL, self.DEPLOY_KEY, "users"))

        assert len(batches) == 2
        assert mock_get.call_count == 2

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_document_deltas_single_page(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "values": [{"_id": "1", "_ts": 200, "_deleted": False}],
            "hasMore": False,
            "cursor": 200,
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        batches = list(document_deltas(self.DEPLOY_URL, self.DEPLOY_KEY, "users", cursor=100))

        assert len(batches) == 1
        assert batches[0][0]["_id"] == "1"

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_document_deltas_includes_deletions(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "values": [
                {"_id": "1", "_ts": 200, "_deleted": False},
                {"_id": "2", "_ts": 201, "_deleted": True},
            ],
            "hasMore": False,
            "cursor": 201,
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        batches = list(document_deltas(self.DEPLOY_URL, self.DEPLOY_KEY, "users", cursor=100))

        assert len(batches) == 1
        assert len(batches[0]) == 2
        assert batches[0][1]["_deleted"] is True

    @parameterized.expand(
        [
            ("auth_failure_401", 401, "Invalid deploy key"),
            ("auth_failure_403", 403, "Invalid deploy key"),
        ]
    )
    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_http_errors(self, _name, status_code, expected_msg, mock_get):
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = {}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        is_valid, error = validate_credentials(self.DEPLOY_URL, self.DEPLOY_KEY)

        assert is_valid is False
        assert expected_msg in error

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_streaming_export_not_enabled(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "code": "StreamingExportNotEnabled",
            "message": "Streaming export is only available on the Convex Professional plan.",
        }
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        is_valid, error = validate_credentials(self.DEPLOY_URL, self.DEPLOY_KEY)

        assert is_valid is False
        assert "Professional plan" in error

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_success(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"users": {}}
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        is_valid, error = validate_credentials(self.DEPLOY_URL, self.DEPLOY_KEY)

        assert is_valid is True
        assert error is None

    @mock.patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        is_valid, error = validate_credentials(self.DEPLOY_URL, self.DEPLOY_KEY)

        assert is_valid is False
        assert "Could not connect" in error

    def test_convex_source_full_refresh(self):
        with mock.patch("posthog.temporal.data_imports.sources.convex.convex.list_snapshot") as mock_snapshot:
            mock_snapshot.return_value = iter([[{"_id": "1", "_ts": 100}]])

            response = convex_source(
                deploy_url=self.DEPLOY_URL,
                deploy_key=self.DEPLOY_KEY,
                table_name="users",
                team_id=1,
                job_id="job1",
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )

            assert response.name == "users"
            assert response.primary_keys == ["_id"]

            batches = list(response.items())
            assert len(batches) == 1
            mock_snapshot.assert_called_once_with(self.DEPLOY_URL, self.DEPLOY_KEY, "users")

    def test_convex_source_incremental(self):
        with mock.patch("posthog.temporal.data_imports.sources.convex.convex.document_deltas") as mock_deltas:
            mock_deltas.return_value = iter([[{"_id": "1", "_ts": 200}]])

            response = convex_source(
                deploy_url=self.DEPLOY_URL,
                deploy_key=self.DEPLOY_KEY,
                table_name="messages",
                team_id=1,
                job_id="job2",
                should_use_incremental_field=True,
                db_incremental_field_last_value=100,
            )

            assert response.name == "messages"

            batches = list(response.items())
            assert len(batches) == 1
            mock_deltas.assert_called_once_with(self.DEPLOY_URL, self.DEPLOY_KEY, "messages", 100)
