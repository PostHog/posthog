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
    StartQueryTimeoutError,
)
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
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
