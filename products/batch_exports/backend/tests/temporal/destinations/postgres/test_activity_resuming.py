import dataclasses

import pytest
import unittest.mock

from temporalio import activity

from posthog.batch_exports.service import BatchExportModel

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    PostgresInsertInputs,
    PostgreSQLHeartbeatDetails,
    insert_into_postgres_activity,
)
from products.batch_exports.backend.temporal.spmc import RecordBatchTaskError
from products.batch_exports.backend.tests.temporal.destinations.postgres.utils import (
    assert_clickhouse_records_in_postgres,
)
from products.batch_exports.backend.tests.temporal.utils.clickhouse import FlakyClickHouseClient

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_insert_into_postgres_activity_completes_range_when_there_is_a_failure(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    interval,
    postgres_batch_export,
    ateam,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    postgres_config,
    model,
):
    """Test that the insert_into_postgres_activity can resume from a failure using heartbeat details."""
    table_name = f"test_insert_activity_table_{ateam.pk}"

    events_to_create, persons_to_create = generate_test_data
    total_records = len(persons_to_create) if model.name == "persons" else len(events_to_create)
    # fail halfway through
    fail_after_records = total_records // 2

    heartbeat_details: list[PostgreSQLHeartbeatDetails] = []

    def track_heartbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        postgres_details = PostgreSQLHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(postgres_details)

    activity_environment.on_heartbeat = track_heartbeat_details

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=model,
        **postgres_config,
    )

    with unittest.mock.patch(
        "posthog.temporal.common.clickhouse.ClickHouseClient",
        lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
    ):
        # We expect this to raise an exception
        with pytest.raises(RecordBatchTaskError):
            await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) > 0
    assert detail.records_completed == fail_after_records

    # Now we resume from the heartbeat
    previous_info = dataclasses.asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )

    activity_environment.info = new_info

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    sort_key = "event" if model.name == "events" else "person_id"

    # Verify all the data for the whole range was exported correctly
    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
        expect_duplicates=True,
        primary_key=["uuid"] if model.name == "events" else ["distinct_id", "person_id"],
    )
