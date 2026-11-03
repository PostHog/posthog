import gc
import io
import random
import string
import asyncio
import weakref
import collections.abc

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import requests
import google.auth.exceptions
from google.api_core.exceptions import (
    Forbidden,
    GatewayTimeout,
    InternalServerError,
    NotFound,
    RetryError,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud import bigquery

from posthog.models.integration.google_cloud import InvalidGoogleTokenUriError

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    BigQueryField,
    BigQueryTable,
    BigQueryType,
    GoogleCloudServiceAccountIntegration,
    StartQueryTimeoutError,
)
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    check_valid_credentials as has_valid_aws_credentials,
)


@pytest.mark.parametrize(
    "states_sequence,should_timeout",
    [
        (["PENDING", "PENDING", "RUNNING", "DONE"], False),
        (["PENDING"] * 100, True),
        (["RUNNING", "DONE"], False),
    ],
    ids=["eventually_starts", "stays_pending_times_out", "starts_immediately"],
)
@pytest.mark.asyncio
async def test_execute_query_pending_timeout(states_sequence: list[str], should_timeout: bool):
    mock_query_job = MagicMock()
    state_iter = iter(states_sequence)
    mock_query_job.state = next(state_iter)
    mock_query_job.job_id = "test-job-id"

    def reload_side_effect():
        try:
            mock_query_job.state = next(state_iter)
        except StopIteration:
            pass

    mock_query_job.reload = reload_side_effect
    mock_result = MagicMock(name="mock_result")
    mock_query_job.result.return_value = mock_result

    mock_sync_client = MagicMock()
    mock_sync_client.query.return_value = mock_query_job
    mock_sync_client.project = "test-project"

    client = BigQueryClient(mock_sync_client)

    if should_timeout:
        with pytest.raises(
            StartQueryTimeoutError, match="Query still in 'PENDING' state after 0.05 seconds; timing out."
        ):
            await client.execute_query(
                "SELECT 1",
                start_query_timeout=0.05,
                poll_interval=0.01,
            )
        mock_query_job.cancel.assert_called_once()
    else:
        result = await client.execute_query(
            "SELECT 1",
            start_query_timeout=0.5,
            poll_interval=0.01,
        )
        assert result == mock_result


def _make_load_test_client(
    reload_outcomes: collections.abc.Sequence[str | Exception],
) -> tuple[BigQueryClient, BigQueryTable, list[int]]:
    mock_sync_client = MagicMock()
    mock_sync_client.project = "test-project"

    load_job = bigquery.LoadJob(
        "test-job-id", None, bigquery.TableReference.from_string("test-project.dataset.table"), mock_sync_client
    )
    load_job._properties["status"] = {"state": "RUNNING"}
    outcomes = iter(reload_outcomes)

    def reload(*args, **kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        load_job._set_properties({**load_job._properties, "status": {"state": outcome}})

    load_job.reload = reload  # type: ignore
    uploads: list[int] = []

    # A plain function rather than a MagicMock, because a mock keeps the file alive in `call_args`.
    def load_table_from_file(file, *args, **kwargs):
        uploads.append(len(file.read()))
        return load_job

    mock_sync_client.load_table_from_file = load_table_from_file

    table = BigQueryTable.from_arrow_schema(
        pa.schema([pa.field("event", pa.string())]),
        project_id="test-project",
        dataset_id="dataset",
        table_id="table",
        primary_key=(),
        version_key=(),
    )
    return BigQueryClient(mock_sync_client), table, uploads


@pytest.mark.parametrize("reloads_until_done", [1, 3])
@pytest.mark.asyncio
async def test_load_file_does_not_keep_file_alive_after_load(reloads_until_done: int):
    client, table, _ = _make_load_test_client(["RUNNING"] * (reloads_until_done - 1) + ["DONE"])
    file = io.BytesIO(b"x" * 1024)
    file_ref = weakref.ref(file)

    gc.disable()
    try:
        await client.load_file(file, format="Parquet", table=table, poll_interval=0.01)
        del file

        assert file_ref() is None
    finally:
        gc.enable()


@pytest.mark.parametrize(
    "reload_outcomes,expected_exception",
    [
        ([ServiceUnavailable("unavailable"), "RUNNING", "DONE"], None),
        ([GatewayTimeout("timeout"), TooManyRequests("slow down"), "DONE"], None),
        ([RetryError("deadline exceeded", cause=InternalServerError("internal")), "DONE"], None),
        ([requests.exceptions.ConnectionError("reset"), requests.exceptions.Timeout("timeout"), "DONE"], None),
        ([google.auth.exceptions.TransportError("token refresh failed"), "DONE"], None),
        ([NotFound("job not found")], NotFound),
        (["RUNNING", Forbidden("forbidden")], Forbidden),
    ],
    ids=[
        "service_unavailable",
        "gateway_timeout_then_too_many_requests",
        "client_retries_exhausted",
        "requests_connection_errors",
        "auth_transport_error",
        "not_found_raises",
        "forbidden_raises",
    ],
)
@pytest.mark.asyncio
async def test_load_file_retries_transient_poll_errors_without_uploading_again(
    reload_outcomes: list[str | Exception], expected_exception: type[Exception] | None
):
    client, table, uploads = _make_load_test_client(reload_outcomes)
    real_sleep = asyncio.sleep

    with patch("asyncio.sleep", side_effect=lambda delay: real_sleep(0)):
        if expected_exception is None:
            await client.load_file(io.BytesIO(b"x"), format="Parquet", table=table, poll_interval=0.01)
        else:
            with pytest.raises(expected_exception):
                await client.load_file(io.BytesIO(b"x"), format="Parquet", table=table, poll_interval=0.01)

    assert len(uploads) == 1


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields,time_partitioning",
    [
        [(BigQueryField("id", BigQueryType("INT64", False), False),), None],
        [
            (
                BigQueryField("id", BigQueryType("INT64", False), False),
                BigQueryField("timestamp", BigQueryType("TIMESTAMP", False), False),
            ),
            bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="timestamp"),
        ],
    ],
)
async def test_create_table(fields, time_partitioning, bigquery_client, bigquery_config, bigquery_dataset):
    """Assert tables are created."""
    table = BigQueryTable(
        f"test_table_{''.join(random.choices(string.ascii_letters, k=10))}",
        fields,
        parents=(bigquery_client.project, bigquery_dataset.dataset_id),
        time_partitioning=time_partitioning,
    )
    client = BigQueryClient(bigquery_client)
    created = await client.create_table(table)

    try:
        assert created.time_partitioning == table.time_partitioning == time_partitioning
        assert all(field.name in created for field in fields)
    finally:
        await client.delete_table(table)


@pytest.mark.asyncio
@pytest.mark.parametrize("versioned", [True, False])
@pytest.mark.parametrize(
    "key,quoted_key,version,quoted_version",
    [
        ("id", "`id`", "version", "`version`"),
        ("group", "`group`", "updated at", "`updated at`"),
        ("key`name", r"`key\`name`", "version\\name", r"`version\\name`"),
        ("key\\`name", r"`key\\\`name`", "version\nname", r"`version\nname`"),
    ],
)
async def test_merge_query_with_optional_version_key(
    versioned: bool, key: str, quoted_key: str, version: str, quoted_version: str
) -> None:
    fields = (
        BigQueryField(key, BigQueryType("INT64", False), False),
        BigQueryField(version, BigQueryType("INT64", False), False),
    )
    final = BigQueryTable(
        "final", fields, ("project", "dataset"), primary_key=(key,), version_key=(version,) if versioned else ()
    )
    stage = BigQueryTable("stage", fields, ("project", "dataset"))
    client = BigQueryClient(MagicMock())

    with patch.object(client, "execute_query", new_callable=AsyncMock) as execute:
        await client.merge_tables(final, stage)

    query = " ".join(execute.call_args.args[0].split())
    assert query.startswith("MERGE `project.dataset.final`")
    assert f"ON final.{quoted_key} = stage.{quoted_key}" in query
    assert (
        f"UPDATE SET final.{quoted_key} = stage.{quoted_key}, final.{quoted_version} = stage.{quoted_version}" in query
    )
    assert f"WHEN NOT MATCHED BY TARGET THEN INSERT ({quoted_key}, {quoted_version})" in query
    assert f"VALUES (stage.{quoted_key}, stage.{quoted_version})" in query
    if versioned:
        assert f"WHEN MATCHED AND (final.{quoted_version} < stage.{quoted_version}) THEN UPDATE" in query
        assert f"PARTITION BY {quoted_key} ORDER BY {quoted_version} DESC" in query
    else:
        assert "WHEN MATCHED THEN UPDATE" in query
        assert f"ROW_NUMBER() OVER ( PARTITION BY {quoted_key} )" in query


@pytest.mark.asyncio
@pytest.mark.parametrize("merge", [True, False])
async def test_write_query_quotes_fields_and_tables_with_json_casts(merge: bool) -> None:
    final = BigQueryTable(
        "final`table",
        (
            BigQueryField("group", BigQueryType("INT64", False), False),
            BigQueryField("json\\`data", BigQueryType("JSON", False), True),
        ),
        ("project", "dataset"),
        primary_key=("group",) if merge else (),
    )
    stage = BigQueryTable(
        "stage\\`table",
        (
            BigQueryField("group", BigQueryType("INT64", False), False),
            BigQueryField("json\\`data", BigQueryType("STRING", False), True),
        ),
        ("project", "dataset"),
    )
    client = BigQueryClient(MagicMock())
    with patch.object(client, "execute_query", new_callable=AsyncMock) as execute:
        await client.merge_tables(final, stage)

    query = " ".join(execute.call_args.args[0].split())
    assert r"`project.dataset.final\`table`" in query
    assert r"FROM `project.dataset.stage\\\`table`" in query
    assert r"`json\\\`data`" in query
    prefix = "stage." if merge else ""
    assert f"REGEXP_REPLACE( {prefix}" + r"`json\\\`data`," in query
    if merge:
        assert r"INSERT (`group`, `json\\\`data`)" in query
    else:
        assert r"(`group`,`json\\\`data`)" in query
        assert "SELECT `group`, SAFE.PARSE_JSON(" in query


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("version_key", [("version",), ()])
async def test_merge_tables_with_multiple_stage_tables(bigquery_client, bigquery_dataset, version_key):
    fields = (
        BigQueryField("id", BigQueryType("INT64", False), False),
        BigQueryField("version", BigQueryType("INT64", False), False),
        BigQueryField("value", BigQueryType("STRING", False), True),
    )
    suffix = "".join(random.choices(string.ascii_letters, k=10))
    parents = (bigquery_client.project, bigquery_dataset.dataset_id)
    final_table = BigQueryTable(
        f"test_merge_final_{suffix}", fields, parents, primary_key=("id",), version_key=version_key
    )
    stage_tables = [
        BigQueryTable(
            f"test_merge_stage_{index}_{suffix}", fields, parents, primary_key=("id",), version_key=version_key
        )
        for index in range(2)
    ]

    client = BigQueryClient(bigquery_client)
    for table in (final_table, *stage_tables):
        await client.create_table(table)

    try:
        # Key 1 tests cross-stage deduplication; key 4 tests whether versions gate replacement.
        await client.execute_query(
            f"INSERT INTO `{final_table.fully_qualified_name}` (id, version, value)"
            " VALUES (1, 1, 'final-v1'), (4, 5, 'final-v5')"
        )
        await client.execute_query(
            f"INSERT INTO `{stage_tables[0].fully_qualified_name}` (id, version, value)"
            " VALUES (1, 2, 'stage0-v2'), (2, 1, 'stage0-only'), (4, 1, 'stage0-v1')"
        )
        await client.execute_query(
            f"INSERT INTO `{stage_tables[1].fully_qualified_name}` (id, version, value)"
            " VALUES (1, 3, 'stage1-v3'), (3, 1, 'stage1-only')"
        )

        await client.merge_tables(final=final_table, stage=stage_tables)

        result = list(
            await client.execute_query(f"SELECT id, version, value FROM `{final_table.fully_qualified_name}`")
        )
        rows = {row["id"]: (row["version"], row["value"]) for row in result}

        assert len(rows) == len(result) == 4
        assert rows.pop(1) in ({(3, "stage1-v3")} if version_key else {(2, "stage0-v2"), (3, "stage1-v3")})
        assert rows == {
            2: (1, "stage0-only"),
            3: (1, "stage1-only"),
            4: (5, "final-v5") if version_key else (1, "stage0-v1"),
        }
    finally:
        for table in (final_table, *stage_tables):
            await client.delete_table(table)


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("integration", ["impersonated", "key_file"], indirect=True)
async def test_from_service_account_integration(
    integration,
):
    """Can initialize client from integration configured."""
    google_integration = GoogleCloudServiceAccountIntegration(integration)
    if not await has_valid_aws_credentials() and not google_integration.has_key():
        pytest.skip("AWS credentials not available and required for impersonated integration")

    client = BigQueryClient.from_service_account_integration(google_integration)
    # This triggers a credential refresh, just to make sure it is correctly set up.
    results = list(client.sync_client.query("SELECT 1").result())

    assert results[0].values()[0] == 1


def test_from_service_account_inputs_rejects_token_uri_that_is_not_google():
    with pytest.raises(InvalidGoogleTokenUriError):
        BigQueryClient.from_service_account_inputs(
            private_key="key",
            private_key_id="key-id",
            token_uri="https://relay.example.com/token",
            client_email="svc@proj.iam.gserviceaccount.com",
            project_id="proj",
        )
