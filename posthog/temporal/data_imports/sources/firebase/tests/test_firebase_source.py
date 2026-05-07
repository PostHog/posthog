import pytest
from unittest import mock

from posthog.schema import (
    ReleaseStatus,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.firebase.firestore import FirebaseResumeConfig
from posthog.temporal.data_imports.sources.firebase.source import FirebaseSource
from posthog.temporal.data_imports.sources.generated_configs import FirebaseKeyFileConfig, FirebaseSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalFieldType


def _make_config(database_id: str | None = None) -> FirebaseSourceConfig:
    return FirebaseSourceConfig(
        key_file=FirebaseKeyFileConfig(
            project_id="my-project",
            private_key="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
            private_key_id="kid",
            client_email="svc@my-project.iam.gserviceaccount.com",
            token_uri="https://oauth2.googleapis.com/token",
        ),
        database_id=database_id,
    )


class TestFirebaseSource:
    def setup_method(self):
        self.source = FirebaseSource()
        self.team_id = 123
        self.config = _make_config()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FIREBASE

    def test_get_source_config_metadata(self):
        config = self.source.get_source_config

        assert config.name.value == "Firebase"
        assert config.label == "Firebase"
        assert config.iconPath == "/static/services/firebase.png"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.featureFlag == "dwh-firebase"
        assert config.unreleasedSource is None
        assert len(config.fields) == 2

    def test_get_source_config_key_file_field(self):
        key_file_field = self.source.get_source_config.fields[0]

        assert isinstance(key_file_field, SourceFieldFileUploadConfig)
        assert key_file_field.name == "key_file"
        assert key_file_field.required is True
        assert isinstance(key_file_field.fileFormat.keys, list)
        assert set(key_file_field.fileFormat.keys) == {
            "project_id",
            "private_key",
            "private_key_id",
            "client_email",
            "token_uri",
        }

    def test_get_source_config_database_id_field(self):
        database_id_field = self.source.get_source_config.fields[1]

        assert isinstance(database_id_field, SourceFieldInputConfig)
        assert database_id_field.name == "database_id"
        assert database_id_field.type == SourceFieldInputConfigType.TEXT
        assert database_id_field.required is False
        assert database_id_field.placeholder == "(default)"

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized",
            "403 Client Error: Forbidden",
            "404 Client Error: Not Found",
        ],
    )
    def test_non_retryable_errors_covers_auth_and_not_found(self, expected_key):
        errors = self.source.get_non_retryable_errors()

        assert expected_key in errors

    def test_get_resumable_source_manager_returns_correct_manager(self):
        inputs = mock.Mock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.logger = mock.Mock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FirebaseResumeConfig

    def test_get_schemas_uses_default_database_when_blank(self):
        with mock.patch(
            "posthog.temporal.data_imports.sources.firebase.source.get_collection_schemas"
        ) as mock_get_schemas:
            mock_get_schemas.return_value = {
                "users": {
                    "columns": [
                        ("_id", "string", False),
                        ("_create_time", "timestamp", False),
                        ("_update_time", "timestamp", False),
                        ("name", "string", True),
                    ],
                    "incremental_fields": [
                        {
                            "label": "_update_time",
                            "type": IncrementalFieldType.Timestamp,
                            "field": "_update_time",
                            "field_type": IncrementalFieldType.Timestamp,
                            "is_indexed": True,
                        }
                    ],
                }
            }

            schemas = self.source.get_schemas(self.config, self.team_id)

            mock_get_schemas.assert_called_once()
            assert mock_get_schemas.call_args.kwargs["database_id"] == "(default)"
            assert len(schemas) == 1
            schema = schemas[0]
            assert schema.name == "users"
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert schema.detected_primary_keys == ["_id"]
            assert any(field["field"] == "_update_time" for field in schema.incremental_fields)

    def test_get_schemas_uses_custom_database_id(self):
        config = _make_config(database_id="prod-db")
        with mock.patch(
            "posthog.temporal.data_imports.sources.firebase.source.get_collection_schemas"
        ) as mock_get_schemas:
            mock_get_schemas.return_value = {}
            self.source.get_schemas(config, self.team_id)

            assert mock_get_schemas.call_args.kwargs["database_id"] == "prod-db"

    def test_validate_credentials_success(self):
        with (
            mock.patch(
                "posthog.temporal.data_imports.sources.firebase.source.validate_service_account_credentials"
            ) as mock_validate,
            mock.patch("posthog.temporal.data_imports.sources.firebase.source.list_collection_ids") as mock_list,
        ):
            mock_validate.return_value = None
            mock_list.return_value = ["users", "orders"]

            valid, error = self.source.validate_credentials(self.config, self.team_id)

            assert valid is True
            assert error is None

    def test_validate_credentials_failure_on_bad_key(self):
        with mock.patch(
            "posthog.temporal.data_imports.sources.firebase.source.validate_service_account_credentials"
        ) as mock_validate:
            mock_validate.side_effect = ValueError(
                "Failed to authenticate with provided Firebase service account key: bad key"
            )

            valid, error = self.source.validate_credentials(self.config, self.team_id)

            assert valid is False
            assert error is not None
            assert "Failed to authenticate" in error

    def test_validate_credentials_failure_on_list_collections(self):
        with (
            mock.patch("posthog.temporal.data_imports.sources.firebase.source.validate_service_account_credentials"),
            mock.patch("posthog.temporal.data_imports.sources.firebase.source.list_collection_ids") as mock_list,
            mock.patch("posthog.temporal.data_imports.sources.firebase.source.capture_exception"),
        ):
            mock_list.side_effect = RuntimeError("boom")

            valid, error = self.source.validate_credentials(self.config, self.team_id)

            assert valid is False
            assert error is not None
            assert "Failed to connect to Firestore" in error

    def test_source_for_pipeline_passes_args_through(self):
        inputs = mock.Mock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "_update_time"
        inputs.db_incremental_field_last_value = None
        inputs.team_id = self.team_id
        inputs.logger = mock.Mock()

        manager = mock.Mock(spec=ResumableSourceManager)

        with mock.patch(
            "posthog.temporal.data_imports.sources.firebase.source.firestore_source"
        ) as mock_firestore_source:
            mock_firestore_source.return_value = mock.sentinel.response
            response = self.source.source_for_pipeline(self.config, manager, inputs)

            assert response is mock.sentinel.response
            kwargs = mock_firestore_source.call_args.kwargs
            assert kwargs["collection_id"] == "users"
            assert kwargs["database_id"] == "(default)"
            assert kwargs["should_use_incremental_field"] is True
            assert kwargs["incremental_field"] == "_update_time"
            assert kwargs["resumable_source_manager"] is manager
