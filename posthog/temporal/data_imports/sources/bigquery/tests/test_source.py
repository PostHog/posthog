import pytest
from freezegun import freeze_time
from unittest import mock

from dateutil import parser
from google.api_core.exceptions import BadRequest, Forbidden, NotFound, PermissionDenied

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_TOKEN_RESPONSE_ERROR,
    BigQueryImplementation,
    BigQueryTokenRefreshError,
    _bq_select_clause,
    _get_query,
    _has_duplicate_primary_keys,
    _resolve_dataset_id,
    _resolve_dataset_project_id,
    _resolve_project_id,
    _resolve_query_project,
    _resolve_region,
    bigquery_storage_read_client,
    delete_all_temp_destination_tables,
    validate_bigquery_credentials,
)
from posthog.temporal.data_imports.sources.bigquery.source import BigQuerySource
from posthog.temporal.data_imports.sources.common.sql.identifiers import InvalidIdentifierError
from posthog.temporal.data_imports.sources.generated_configs import (
    BigQueryDatasetProjectConfig,
    BigQueryKeyFileConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
    BigQueryUseCustomRegionConfig,
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
    project_id: str = "project-id",
    dataset_id: str = "dataset-id",
    dataset_project: BigQueryDatasetProjectConfig | None = None,
    temporary_dataset: BigQueryTemporaryDatasetConfig | None = None,
) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id=project_id,
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id=dataset_id,
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


def test_bigquery_get_columns_returns_empty_when_job_create_forbidden():
    """A service account without `bigquery.jobs.create` raises `Forbidden` from
    `client.query()` (which eagerly creates the job), not from `result()`. That must
    degrade to no schemas rather than crashing schema discovery."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = Forbidden(
        "Access Denied: Project p: User does not have bigquery.jobs.create permission in project p."
    )

    columns = BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)
    assert columns == {}


@pytest.mark.parametrize(
    "error_message,expected_type,is_token_refresh",
    [
        # A bad OAuth token endpoint makes google-auth raise this opaque `TypeError` during the
        # lazy token refresh — `get_columns` must surface a clear, non-retryable error instead.
        ("string indices must be integers, not 'str'", BigQueryTokenRefreshError, True),
        # Any other `TypeError` indicates a genuine bug and must propagate unchanged.
        ("unrelated bug", TypeError, False),
    ],
)
def test_bigquery_get_columns_typeerror_handling(error_message, expected_type, is_token_refresh):
    """Token-refresh `TypeError`s are wrapped as `BigQueryTokenRefreshError`; others propagate."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = TypeError(error_message)

    with pytest.raises(expected_type) as exc_info:
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)

    assert isinstance(exc_info.value, BigQueryTokenRefreshError) == is_token_refresh
    if is_token_refresh:
        # The raised message must carry the stable marker registered as non-retryable.
        assert BIGQUERY_TOKEN_RESPONSE_ERROR in str(exc_info.value)
        assert BIGQUERY_TOKEN_RESPONSE_ERROR in BigQuerySource().get_non_retryable_errors()
    else:
        assert error_message in str(exc_info.value)


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
    "field_type,last_value,expected_clause,offset_present",
    [
        # DATETIME columns are timezone-naive — a tz-aware literal can't be cast and BigQuery rejects it
        # with "Could not cast literal ... to type DATETIME". On the first incremental sync the cursor
        # defaults to the 1970-01-01 UTC initial value, whose isoformat carries a '+00:00' offset; for a
        # DATETIME field the literal must be naive.
        (IncrementalFieldType.DateTime, None, "WHERE `cursor` > '1970-01-01T00:00:00'", False),
        # A tz-aware value carried over from a previous sync is also rendered naive for DATETIME fields.
        (
            IncrementalFieldType.DateTime,
            parser.parse("2024-03-11T09:26:04+00:00"),
            "WHERE `cursor` > '2024-03-11T09:26:04'",
            False,
        ),
        # TIMESTAMP columns are timezone-aware, so the offset must be preserved in the literal.
        (IncrementalFieldType.Timestamp, None, "WHERE `cursor` > '1970-01-01T00:00:00+00:00'", True),
    ],
)
def test_bigquery_get_query_datetime_cursor_timezone_offset(field_type, last_value, expected_clause, offset_present):
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    query = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=last_value,
        bq_table=bq_table,
        incremental_field="cursor",
        incremental_field_type=field_type,
    )
    assert expected_clause in query
    assert ("+00:00" in query) is offset_present


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


@pytest.mark.parametrize(
    "observed_error",
    [
        # Rotated/revoked service account private key.
        "('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant', 'error_description': 'Invalid JWT Signature.'})",
        # Deleted service account.
        "('invalid_grant: Invalid grant: account not found', {'error': 'invalid_grant', 'error_description': 'Invalid grant: account not found'})",
    ],
)
def test_non_retryable_errors_match_rejected_credentials(observed_error):
    """A `RefreshError` carrying the OAuth2 `invalid_grant` code means Google rejected the
    service account grant — retrying can't recover, so the sync must be disabled."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


@pytest.mark.parametrize(
    "transient_error",
    [
        # A token refresh that failed for a transient reason must stay retryable.
        "RefreshError: ('Failed to retrieve token', {'error': 'internal_failure'})",
        "RefreshError: HTTPError 503 Service Unavailable",
    ],
)
def test_non_retryable_errors_does_not_match_transient_refresh_failures(transient_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert not any(key in transient_error for key in non_retryable_errors)


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
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
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


# Regression: a stray leading/trailing space in a hand-entered project or dataset ID made
# every BigQuery request fail with an opaque `BadRequest: Invalid project ID ' ...'` /
# `Invalid dataset ID ' ...'`. The identifiers must be trimmed before reaching BigQuery.


@pytest.mark.parametrize(
    "resolver,field,raw,expected",
    [
        (_resolve_project_id, "project_id", " 524098457564", "524098457564"),
        (_resolve_project_id, "project_id", "project-id\n", "project-id"),
        (_resolve_dataset_id, "dataset_id", " bigquery_aloalo ", "bigquery_aloalo"),
        (_resolve_dataset_id, "dataset_id", "\tdataset-id", "dataset-id"),
    ],
)
def test_bigquery_resolvers_trim_whitespace(resolver, field, raw, expected):
    config = _make_config(**{field: raw})
    assert resolver(config) == expected


def test_bigquery_resolve_region_trims_and_treats_whitespace_as_unset():
    assert (
        _resolve_region(_make_config(dataset_project=None)) is None  # no custom region configured
    )

    config = _make_config()
    config.use_custom_region = BigQueryUseCustomRegionConfig(region="  us-east1 ", enabled=True)
    assert _resolve_region(config) == "us-east1"

    config.use_custom_region = BigQueryUseCustomRegionConfig(region="   ", enabled=True)
    assert _resolve_region(config) is None


def test_bigquery_resolve_dataset_project_id_trims_and_treats_whitespace_as_unset():
    config = _make_config(
        dataset_project=BigQueryDatasetProjectConfig(dataset_project_id="  other-project ", enabled=True)
    )
    assert _resolve_dataset_project_id(config) == "other-project"

    config = _make_config(dataset_project=BigQueryDatasetProjectConfig(dataset_project_id="   ", enabled=True))
    assert _resolve_dataset_project_id(config) is None


def test_bigquery_resolve_query_project_prefers_dataset_project():
    config = _make_config(
        project_id=" service-account-project ",
        dataset_project=BigQueryDatasetProjectConfig(dataset_project_id=" dataset-project ", enabled=True),
    )
    assert _resolve_query_project(config) == "dataset-project"

    config = _make_config(project_id=" service-account-project ")
    assert _resolve_query_project(config) == "service-account-project"


def test_bigquery_get_columns_trims_whitespace_in_identifiers():
    """`get_columns` must not embed a leading space into the INFORMATION_SCHEMA query
    or the `project` it runs against."""
    fake_client = mock.MagicMock()
    fake_client.query.return_value.result.return_value = []

    config = _make_config(project_id=" 524098457564", dataset_id=" bigquery_aloalo ")
    BigQueryImplementation().get_columns(fake_client, config, names=None)

    sql = fake_client.query.call_args.args[0]
    assert "`bigquery_aloalo.INFORMATION_SCHEMA.COLUMNS`" in sql
    assert " bigquery_aloalo" not in sql
    assert fake_client.query.call_args.kwargs["project"] == "524098457564"


def test_bigquery_get_primary_keys_trims_whitespace_in_identifiers():
    fake_client = mock.MagicMock()
    fake_client.query.return_value.result.return_value = []

    config = _make_config(project_id=" my-project ", dataset_id=" my_dataset ")
    BigQueryImplementation().get_primary_keys(fake_client, config, tables=["t"])

    sql = fake_client.query.call_args.args[0]
    assert "`my_dataset`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS" in sql
    assert " my_dataset`" not in sql
    assert fake_client.query.call_args.kwargs["project"] == "my-project"


def test_bigquery_validate_credentials_trims_whitespace_before_calling_bigquery():
    bq = mock.MagicMock()
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.bigquery.bigquery_client", return_value=client_cm
    ) as mock_client:
        validate_bigquery_credentials(
            dataset_id=" my_dataset ",
            key_file={
                "project_id": " 524098457564",
                "private_key": "private-key",
                "private_key_id": "private-key-id",
                "client_email": "client-email",
                "token_uri": "token-uri",
            },
            dataset_project_id=None,
            location=None,
        )

    assert mock_client.call_args.args[0] == "524098457564"
    bq.dataset.assert_called_once_with("my_dataset", project="524098457564")


def test_bigquery_build_pipeline_trims_whitespace_in_destination_table():
    """Whitespace in project/dataset IDs must not leak into the fully-qualified
    destination table name passed to BigQuery during a sync."""
    config = _make_config(project_id=" 524098457564", dataset_id=" bigquery_aloalo ")
    expected_table_id = (
        f"524098457564.bigquery_aloalo.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all,
        mock.patch.object(BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete,
    ):
        BigQuerySource().source_for_pipeline(config, _make_inputs())

    assert mock_delete_all.call_args.kwargs["project_id"] == "524098457564"
    assert mock_delete_all.call_args.kwargs["dataset_id"] == "bigquery_aloalo"
    assert mock_delete.call_args.kwargs["table_id"] == expected_table_id


@pytest.mark.parametrize(
    "observed_error",
    [
        # Storage Read API permission failure — `str(PermissionDenied)` is "403 Access Denied: ..."
        str(
            PermissionDenied(
                "Access Denied: Table prj:ds.fct__conversions: Permission bigquery.tables.getData "
                "denied on table prj:ds.fct__conversions (or it may not exist)."
            )
        ),
        # Permission to list tables in a dataset is also denied with the same prefix
        str(Forbidden("Access Denied: Permission bigquery.tables.list denied on dataset prj:ds.")),
    ],
)
def test_non_retryable_errors_match_permission_denied(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


@pytest.mark.parametrize(
    "other_error",
    [
        # Transient server / connection errors must stay retryable
        "503 Service unavailable, please retry",
        "500 Internal error encountered",
        "Connection reset by peer",
    ],
)
def test_non_retryable_errors_does_not_match_transient(other_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert not any(key in other_error for key in non_retryable_errors)


def _run_has_duplicate_primary_keys(side_effect):
    table = mock.MagicMock()
    table.dataset_id = "dataset"
    table.table_id = "table"
    table.project = "project"

    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.side_effect = side_effect
    client.query.return_value = job

    with mock.patch("posthog.temporal.data_imports.sources.bigquery.bigquery.capture_exception") as mock_capture:
        result = _has_duplicate_primary_keys(table, client, ["id"])
    return result, mock_capture


@pytest.mark.parametrize(
    "exception",
    [
        BadRequest(
            "Resources exceeded during query execution: The query could not be executed in the allotted memory."
        ),
        BadRequest("query failed", errors=[{"reason": "resourcesExceeded", "message": "out of memory"}]),
    ],
)
def test_has_duplicate_primary_keys_skips_resource_exceeded_quietly(exception):
    """A `resourcesExceeded` BigQuery error during the best-effort duplicate-key probe must NOT
    be captured to error tracking — it's a non-actionable data-volume limit that otherwise fires
    on every sync of a large table."""
    result, mock_capture = _run_has_duplicate_primary_keys(exception)

    assert result is False
    mock_capture.assert_not_called()


def test_has_duplicate_primary_keys_captures_unexpected_bad_request():
    """A non-resource BadRequest (e.g. a genuinely malformed probe query) is still captured so we
    don't lose visibility into real bugs."""
    result, mock_capture = _run_has_duplicate_primary_keys(BadRequest("Syntax error in query"))

    assert result is False
    mock_capture.assert_called_once()


def test_has_duplicate_primary_keys_captures_unexpected_errors():
    """Genuinely unexpected errors are still captured so we don't lose visibility."""
    result, mock_capture = _run_has_duplicate_primary_keys(RuntimeError("boom"))

    assert result is False
    mock_capture.assert_called_once()


@pytest.mark.parametrize(
    "location",
    ["US", "EU", "asia-northeast1"],
)
def test_bigquery_dataset_not_found_in_location_is_non_retryable(location):
    """A deleted/renamed dataset (or one in a region we don't query) surfaces from schema
    discovery as a google-api-core NotFound. Its str() is "404 Not found: Dataset ... was
    not found in location <X>", which must be recognised as non-retryable via the
    "was not found in location" pattern instead of retrying forever."""
    error = NotFound(
        f"Not found: Dataset my-proj:my_dataset was not found in location {location}; "
        f"reason: notFound, message: Not found: Dataset my-proj:my_dataset was not found in location {location}"
    )

    # Mirror the substring match in `sync_new_schemas_activity` / `update_external_data_job_model`.
    error_msg = str(error)
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()

    assert any(pattern in error_msg for pattern in non_retryable_errors)


def test_bigquery_storage_read_client_raises_grpc_message_size_limit():
    """The manually-built Storage Read channel must lift gRPC's default 4 MiB receive
    limit, otherwise large `ReadRowsResponse` messages raise `ResourceExhausted`."""
    base = "posthog.temporal.data_imports.sources.bigquery.bigquery"
    with (
        mock.patch(f"{base}.service_account"),
        mock.patch(f"{base}.BigQueryReadGrpcTransport") as mock_transport,
        mock.patch(f"{base}.make_tracked_channel", side_effect=lambda channel, host: channel),
        mock.patch(f"{base}.bigquery_storage"),
    ):
        with bigquery_storage_read_client(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ):
            pass

    options = dict(mock_transport.create_channel.call_args.kwargs["options"])
    assert options["grpc.max_receive_message_length"] == -1
    assert options["grpc.max_send_message_length"] == -1
