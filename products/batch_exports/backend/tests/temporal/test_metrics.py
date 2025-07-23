import datetime as dt
import uuid
from unittest import mock

import psycopg
import pytest
import pytest_asyncio
import temporalio.client
from django.conf import settings
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportModel,
)
from posthog.constants import BATCH_EXPORTS_TASK_QUEUE
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
)
from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    PostgresBatchExportInputs,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.fixture
def table_name(ateam, interval):
    return f"test_table_{ateam.pk}_{interval}"


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "exports_test_database",
        "schema": "exports_test_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(postgres_config, setup_postgres_test_db):
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        autocommit=True,
    )

    yield connection

    await connection.close()


@pytest_asyncio.fixture
async def postgres_batch_export(ateam, table_name, postgres_config, interval, exclude_events, temporal_client):
    destination_data = {
        "type": "Postgres",
        "config": {**postgres_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-postgres-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


async def test_interceptor_calls_histogram_metrics(
    ateam,
    data_interval_end,
    interval,
    postgres_batch_export,
    temporal_client: temporalio.client.Client,
    temporal_worker,
):
    """Test metrics interceptor calls mocked histogram metrics."""

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=BatchExportModel(name="events", schema=None),
        **postgres_batch_export.destination.config,
    )

    with mock.patch(
        "products.batch_exports.backend.temporal.metrics.get_metric_meter", mock.MagicMock()
    ) as mocked_meter:
        await temporal_client.execute_workflow(
            "postgres-export",
            inputs,
            id=workflow_id,
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
            execution_timeout=dt.timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        mocked_meter.assert_any_call(
            {
                "interval": "hour",
                "status": "COMPLETED",
                "exception": "",
            }
        )

        mocked_meter.return_value.create_histogram.assert_any_call(
            name="batch_exports_activity_attempt",
            description="Histogram tracking attempts made by critical batch export activities",
        )
        mocked_meter.return_value.create_histogram_timedelta.assert_any_call(
            name="batch_exports_activity_interval_execution_latency",
            description="Histogram tracking execution latency for critical batch export activities separated by interval",
            unit="ms",
        )
        mocked_meter.return_value.create_histogram_timedelta.assert_any_call(
            name="batch_exports_workflow_interval_execution_latency",
            description="Histogram tracking execution latency for batch export workflows by interval",
            unit="ms",
        )

        number_of_record_calls = len(
            mocked_meter.return_value.create_histogram_timedelta.return_value.record.mock_calls
        )
        assert (
            number_of_record_calls == 2
        ), f"expected to have recorded two metrics: for workflow and activity execution latency, but only found {number_of_record_calls}"

        mocked_meter.return_value.create_histogram.return_value.record.assert_called_once_with(1)
