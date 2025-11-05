import uuid
import asyncio
import datetime as dt

import pytest
from unittest import mock

from django.conf import settings

import psycopg
import temporalio.client
from structlog.testing import capture_logs
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BatchExportModel
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgresBatchExportInputs
from products.batch_exports.backend.temporal.metrics import SLAWaiter

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


@pytest.fixture
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


@pytest.fixture
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
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
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
        mocked_meter.return_value.create_histogram_timedelta.assert_any_call(
            name="batch_exports_workflow_interval_execution_latency",
            description="Histogram tracking execution latency for batch export workflows by interval",
            unit="ms",
        )
        mocked_meter.return_value.create_histogram_timedelta.assert_any_call(
            name="batch_exports_activity_interval_execution_latency",
            description="Histogram tracking execution latency for critical batch export activities by interval",
            unit="ms",
        )

        mocked_meter.return_value.create_counter.assert_any_call(
            name="batch_exports_activity_attempts",
            description="Counter tracking every attempt at running an activity",
        )
        mocked_meter.return_value.create_counter.assert_any_call(
            name="batch_exports_activity_success_attempts",
            description="Counter tracking the attempts it took to complete activities",
        )

        number_of_record_calls = mocked_meter.return_value.create_histogram_timedelta.return_value.record.call_count
        assert (
            number_of_record_calls == 2
        ), f"expected to have recorded two metrics: for workflow and activity execution latency, but only found {number_of_record_calls}"

        number_of_add_calls = mocked_meter.return_value.create_counter.return_value.add.call_count
        expected_calls = [mock.call(1)] * number_of_add_calls

        assert mocked_meter.return_value.create_counter.return_value.add.mock_calls == expected_calls


async def test_sla_waiter():
    with capture_logs() as cap_logs:
        async with SLAWaiter(batch_export_id="test", sla=dt.timedelta(seconds=1)) as detector:
            await asyncio.sleep(3)

            assert detector.is_over_sla()

    assert "SLA breached" == cap_logs[0]["event"]
    assert "test" == cap_logs[0]["batch_export_id"]
    assert 1 == cap_logs[0]["sla_seconds"]

    with capture_logs() as cap_logs:
        async with SLAWaiter(batch_export_id="test", sla=dt.timedelta(seconds=3)) as detector:
            await asyncio.sleep(1)

            assert detector.is_over_sla() is False

    assert not cap_logs
