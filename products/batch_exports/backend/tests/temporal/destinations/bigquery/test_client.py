import random
import string

import pytest
from unittest.mock import MagicMock

from google.cloud import bigquery

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


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
async def test_merge_tables_with_multiple_stage_tables(bigquery_client, bigquery_dataset):
    fields = (
        BigQueryField("id", BigQueryType("INT64", False), False),
        BigQueryField("version", BigQueryType("INT64", False), False),
        BigQueryField("value", BigQueryType("STRING", False), True),
    )
    suffix = "".join(random.choices(string.ascii_letters, k=10))
    parents = (bigquery_client.project, bigquery_dataset.dataset_id)
    final_table = BigQueryTable(
        f"test_merge_final_{suffix}", fields, parents, primary_key=("id",), version_key=("version",)
    )
    stage_tables = [
        BigQueryTable(
            f"test_merge_stage_{index}_{suffix}", fields, parents, primary_key=("id",), version_key=("version",)
        )
        for index in range(2)
    ]

    client = BigQueryClient(bigquery_client)
    for table in (final_table, *stage_tables):
        await client.create_table(table)

    try:
        # Key 1 exists in final and in both stage tables: the highest version across all
        # stage tables must win. Key 4 is newer in final than in stage: it must not be
        # overwritten.
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

        result = await client.execute_query(f"SELECT id, version, value FROM `{final_table.fully_qualified_name}`")
        rows = {row["id"]: (row["version"], row["value"]) for row in result}

        assert rows == {
            1: (3, "stage1-v3"),
            2: (1, "stage0-only"),
            3: (1, "stage1-only"),
            4: (5, "final-v5"),
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
