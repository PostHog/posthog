import pytest
from freezegun import freeze_time
from unittest import mock

from dateutil import parser
from google.api_core.exceptions import Forbidden, NotFound
from google.auth import credentials as google_auth_credentials

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_SCOPES,
    BigQueryAuthInfo,
    BigQueryImplementation,
    _bq_select_clause,
    _get_query,
    delete_all_temp_destination_tables,
    resolve_bigquery_auth,
    validate_bigquery_credentials,
)
from posthog.temporal.data_imports.sources.bigquery.source import BigQuerySource
from posthog.temporal.data_imports.sources.common.sql.identifiers import InvalidIdentifierError
from posthog.temporal.data_imports.sources.generated_configs import (
    BigQueryDatasetProjectConfig,
    BigQueryKeyFileConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
)

from products.data_warehouse.backend.types import IncrementalFieldType


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "schema",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


def _make_config(
    *,
    dataset_project: BigQueryDatasetProjectConfig | None = None,
    temporary_dataset: BigQueryTemporaryDatasetConfig | None = None,
) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=dataset_project,
        temporary_dataset=temporary_dataset,
    )


def test_bigquery_get_columns_filters_existing_destination_tables():
    """`get_columns` strips `__posthog_import_*` tables before returning."""
    fake_client = mock.MagicMock()
    fake_row_keep = mock.MagicMock(table_name="table", column_name="c", data_type="STRING", is_nullable="NO")
    fake_row_skip = mock.MagicMock(
        table_name="__posthog_import_0000_0000", column_name="c", data_type="STRING", is_nullable="NO"
    )
    fake_client.query.return_value.result.return_value = [fake_row_keep, fake_row_skip]

    columns = BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)
    assert list(columns.keys()) == ["table"]


@pytest.mark.parametrize(
    "job_inputs,expected_valid",
    [
        (
            {"dataset_id": "dataset-id", "google_cloud_service_account_integration_id": 1},
            True,
        ),
        (
            {
                "dataset_id": "dataset-id",
                "key_file": {
                    "project_id": "project-id",
                    "private_key": "private-key",
                    "private_key_id": "private-key-id",
                    "client_email": "client-email",
                    "token_uri": "token-uri",
                },
            },
            True,
        ),
        (
            {"dataset_id": "dataset-id"},
            False,
        ),
    ],
)
def test_bigquery_validate_config_accepts_integration_or_key_file(job_inputs, expected_valid):
    is_valid, errors = BigQuerySource().validate_config(job_inputs)
    assert is_valid is expected_valid
    if not expected_valid:
        assert any("google_cloud_service_account_integration_id" in err for err in errors)


def test_bigquery_validate_credentials_surfaces_auth_resolution_error():
    config = _make_config()
    expected_error = "Google Cloud impersonation is not configured on this instance"

    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.source.resolve_bigquery_auth",
        side_effect=ValueError(expected_error),
    ):
        is_valid, error = BigQuerySource().validate_credentials(config, team_id=1)

    assert is_valid is False
    assert error == expected_error


def test_bigquery_validate_credentials_surfaces_validation_error():
    config = _make_config()
    auth = BigQueryAuthInfo(
        project_id="project-id",
        credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
    )
    expected_error = "BigQuery dataset 'dataset-id' was not found in project 'project-id'."

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.resolve_bigquery_auth",
            return_value=auth,
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.validate_bigquery_credentials",
            return_value=(False, expected_error),
        ),
    ):
        is_valid, error = BigQuerySource().validate_credentials(config, team_id=1)

    assert is_valid is False
    assert error == expected_error


def test_bigquery_validate_credentials_success():
    config = _make_config()
    auth = BigQueryAuthInfo(
        project_id="project-id",
        credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
    )

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.resolve_bigquery_auth",
            return_value=auth,
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.validate_bigquery_credentials",
            return_value=(True, None),
        ),
    ):
        is_valid, error = BigQuerySource().validate_credentials(config, team_id=1)

    assert is_valid is True
    assert error is None


def test_resolve_bigquery_auth_uses_integration_key_when_present():
    config = BigQuerySourceConfig.from_dict(
        {
            "dataset_id": "dataset-id",
            "google_cloud_service_account_integration_id": 42,
            "key_file": {
                "project_id": "project-id",
                "private_key": "private-key",
                "private_key_id": "private-key-id",
                "client_email": "client-email",
                "token_uri": "token-uri",
            },
        }
    )
    mock_integration = mock.MagicMock()
    mock_integration.kind = "google-cloud-service-account"
    gcp_integration = mock.MagicMock()
    gcp_integration.has_key.return_value = True
    gcp_integration.service_account_info = {
        "project_id": "project-id",
        "private_key": "private-key",
        "private_key_id": "private-key-id",
        "client_email": "client-email",
        "token_uri": "token-uri",
    }
    gcp_integration.project_id = "project-id"

    with (
        mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.Integration.objects.filter") as mock_filter,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.GoogleCloudServiceAccountIntegration",
            return_value=gcp_integration,
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.service_account.Credentials.from_service_account_info",
            return_value=mock.sentinel.service_account_credentials,
        ) as mock_from_info,
    ):
        mock_filter.return_value.first.return_value = mock_integration
        auth = resolve_bigquery_auth(config, team_id=1)

    assert auth.project_id == "project-id"
    assert auth.credentials is mock.sentinel.service_account_credentials
    mock_from_info.assert_called_once_with(gcp_integration.service_account_info, scopes=BIGQUERY_SCOPES)


def test_resolve_bigquery_auth_uses_impersonation_when_integration_has_no_key():
    config = BigQuerySourceConfig.from_dict(
        {
            "dataset_id": "dataset-id",
            "google_cloud_service_account_integration_id": 42,
            "key_file": {
                "project_id": "project-id",
                "private_key": "private-key",
                "private_key_id": "private-key-id",
                "client_email": "client-email",
                "token_uri": "token-uri",
            },
        }
    )
    mock_integration = mock.MagicMock()
    mock_integration.kind = "google-cloud-service-account"
    gcp_integration = mock.MagicMock()
    gcp_integration.has_key.return_value = False
    gcp_integration.service_account_email = "service-account@project-id.iam.gserviceaccount.com"
    gcp_integration.project_id = "project-id"

    with (
        mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.Integration.objects.filter") as mock_filter,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.GoogleCloudServiceAccountIntegration",
            return_value=gcp_integration,
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery._get_posthog_google_cloud_credentials",
            return_value=mock.sentinel.posthog_google_credentials,
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.google_auth_impersonated_credentials.Credentials",
            return_value=mock.sentinel.impersonated_credentials,
        ) as mock_impersonated_credentials,
    ):
        mock_filter.return_value.first.return_value = mock_integration
        auth = resolve_bigquery_auth(config, team_id=1)

    assert auth.project_id == "project-id"
    assert auth.credentials is mock.sentinel.impersonated_credentials
    mock_impersonated_credentials.assert_called_once_with(
        source_credentials=mock.sentinel.posthog_google_credentials,
        target_principal="service-account@project-id.iam.gserviceaccount.com",
        target_scopes=BIGQUERY_SCOPES,
        lifetime=3600,
    )


def test_bigquery_connect_resolves_integration_auth_when_team_id_is_provided():
    config = BigQuerySourceConfig.from_dict(
        {
            "dataset_id": "dataset-id",
            "google_cloud_service_account_integration_id": 42,
        }
    )
    auth = BigQueryAuthInfo(
        project_id="project-id",
        credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
    )
    mocked_client = mock.MagicMock()
    mocked_client_cm = mock.MagicMock()
    mocked_client_cm.__enter__.return_value = mocked_client
    mocked_client_cm.__exit__.return_value = None

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.resolve_bigquery_auth",
            return_value=auth,
        ) as mock_resolve_auth,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.bigquery_client",
            return_value=mocked_client_cm,
        ) as mock_bigquery_client,
    ):
        with BigQueryImplementation().connect(config, team_id=1) as conn:
            assert conn is mocked_client

    mock_resolve_auth.assert_called_once_with(config, 1)
    mock_bigquery_client.assert_called_once_with("project-id", None, auth.credentials)


def test_bigquery_connect_requires_team_id_argument():
    config = BigQuerySourceConfig.from_dict(
        {
            "dataset_id": "dataset-id",
            "google_cloud_service_account_integration_id": 42,
        }
    )

    with pytest.raises(TypeError):
        with BigQueryImplementation().connect(config):
            pass


@pytest.mark.parametrize(
    "dataset_project,temporary_dataset,expected_dataset_project_id,expected_destination_dataset_id",
    [
        # default — no dataset_project, no temporary_dataset
        (None, None, None, "dataset-id"),
        # dataset_project enabled — propagated through both delete_all and _build_source_response
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            None,
            "other-project-id",
            "dataset-id",
        ),
        # temporary_dataset enabled — overrides destination_table_dataset_id
        (
            None,
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            None,
            "some-other-dataset-id",
        ),
        # both set — temporary_dataset wins for destination, dataset_project still resolved
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            "other-project-id",
            "some-other-dataset-id",
        ),
    ],
)
def test_bigquery_build_pipeline_resolves_dataset_routing(
    dataset_project, temporary_dataset, expected_dataset_project_id, expected_destination_dataset_id
):
    config = _make_config(dataset_project=dataset_project, temporary_dataset=temporary_dataset)
    expected_table_id = (
        f"project-id.{expected_destination_dataset_id}.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.resolve_bigquery_auth",
            return_value=BigQueryAuthInfo(
                project_id="project-id",
                credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
            ),
        ),
        mock.patch.object(
            BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()
        ) as mock_build,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete,
    ):
        BigQuerySource().source_for_pipeline(config, _make_inputs())

    assert mock_delete_all.call_args.kwargs["dataset_id"] == expected_destination_dataset_id
    assert mock_delete_all.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_delete_all.call_args.kwargs["table_prefix"] == "__posthog_import_schema_id"

    assert mock_build.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_build.call_args.kwargs["bq_destination_table_id"] == expected_table_id

    assert mock_delete.call_args.kwargs["table_id"] == expected_table_id


@pytest.mark.parametrize(
    "enabled_columns,primary_keys,incremental_field,expected",
    [
        (None, ["id"], None, "*"),
        (["email"], ["id"], None, "`email`, `id`"),
        (["email"], ["id"], "created_at", "`email`, `id`, `created_at`"),
        ([], None, None, "*"),
        ([], ["id"], None, "`id`"),
    ],
)
def test_bigquery_select_clause(enabled_columns, primary_keys, incremental_field, expected):
    assert _bq_select_clause(enabled_columns, primary_keys, incremental_field) == expected


def test_bigquery_get_query_projects_enabled_columns():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    query = _get_query(
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        bq_table=bq_table,
        enabled_columns=["email"],
        primary_keys=["id"],
    )
    assert "SELECT `email`, `id` FROM" in query


def test_bigquery_get_query_keeps_incremental_field_in_projection():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    query = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=42,
        bq_table=bq_table,
        incremental_field="updated_at",
        incremental_field_type=IncrementalFieldType.Integer,
        enabled_columns=["email"],
        primary_keys=["id"],
    )
    assert "SELECT `email`, `id`, `updated_at` FROM" in query
    assert "WHERE `updated_at` > 42" in query


@pytest.mark.parametrize(
    "malicious_column",
    [
        "x` FROM `other.private` --",
        "id; DROP TABLE customers",
        "email`, `secret",
        "name with space",
        "col\x00null",
    ],
)
def test_bigquery_select_clause_rejects_injection_attempts(malicious_column):
    """`enabled_columns` flows from user config — must be allowlisted before backtick quoting."""
    with pytest.raises(InvalidIdentifierError):
        _bq_select_clause([malicious_column], primary_keys=None, incremental_field=None)


def _run_delete_all_temp_destination_tables(side_effect, logger):
    bq = mock.MagicMock()
    bq.list_tables.side_effect = side_effect
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with (
        mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.bigquery_client", return_value=client_cm),
        mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.capture_exception") as mock_capture,
    ):
        delete_all_temp_destination_tables(
            dataset_id="dataset-id",
            table_prefix="prefix_",
            project_id="project-id",
            location=None,
            dataset_project_id=None,
            credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
            logger=logger,
        )
    return mock_capture


@pytest.mark.parametrize(
    "exception",
    [
        Forbidden("Access Denied: Permission bigquery.tables.list denied on dataset"),
        NotFound("Dataset not found (or it may not exist)"),
    ],
)
def test_delete_all_temp_destination_tables_swallows_expected_errors_quietly(exception):
    """Lost permissions or a deleted dataset during best-effort cleanup must NOT be
    captured to error tracking — it's expected and fires on every sync otherwise."""
    logger = mock.MagicMock()

    mock_capture = _run_delete_all_temp_destination_tables(exception, logger)

    mock_capture.assert_not_called()
    logger.warning.assert_called_once()


def test_delete_all_temp_destination_tables_captures_unexpected_errors():
    """Genuinely unexpected errors are still captured so we don't lose visibility."""
    logger = mock.MagicMock()

    mock_capture = _run_delete_all_temp_destination_tables(RuntimeError("boom"), logger)

    mock_capture.assert_called_once()


def _run_validate_bigquery_credentials(
    side_effect: Exception,
    *,
    dataset_project_id: str | None = None,
):
    bq = mock.MagicMock()
    bq.list_tables.side_effect = side_effect
    bq.dataset.return_value = mock.sentinel.dataset_ref

    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.bigquery_client",
            return_value=client_cm,
        ),
        mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.capture_exception") as mock_capture,
    ):
        is_valid, error = validate_bigquery_credentials(
            dataset_id="dataset-id",
            project_id="project-id",
            credentials=mock.MagicMock(spec=google_auth_credentials.Credentials),
            dataset_project_id=dataset_project_id,
            location=None,
        )

    return is_valid, error, mock_capture


def test_validate_bigquery_credentials_reports_not_found():
    is_valid, error, mock_capture = _run_validate_bigquery_credentials(
        NotFound("Dataset was not found"),
        dataset_project_id="dataset-project-id",
    )

    assert is_valid is False
    assert error == "BigQuery dataset 'dataset-id' was not found in project 'dataset-project-id'."
    mock_capture.assert_not_called()


def test_validate_bigquery_credentials_reports_permission_denied():
    is_valid, error, mock_capture = _run_validate_bigquery_credentials(
        Forbidden("Permission denied"),
        dataset_project_id="dataset-project-id",
    )

    assert is_valid is False
    assert error == "Permission denied while accessing BigQuery dataset 'dataset-id' in project 'dataset-project-id'."
    mock_capture.assert_not_called()


def test_validate_bigquery_credentials_reports_unexpected_errors():
    is_valid, error, mock_capture = _run_validate_bigquery_credentials(RuntimeError("boom"))

    assert is_valid is False
    assert error == "Failed to validate BigQuery credentials"
    mock_capture.assert_called_once()
