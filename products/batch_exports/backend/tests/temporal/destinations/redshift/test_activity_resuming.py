import uuid
import datetime as dt
import operator

import pytest

import temporalio.common
from temporalio import activity

from posthog.batch_exports.service import BatchExportModel

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    RedshiftInsertInputs,
    insert_into_redshift_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import (
    assert_clickhouse_records_in_redshift,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize(
    "done_relative_ranges,expected_relative_ranges",
    [
        (
            [(dt.timedelta(minutes=0), dt.timedelta(minutes=15))],
            [(dt.timedelta(minutes=15), dt.timedelta(minutes=60))],
        ),
        (
            [
                (dt.timedelta(minutes=10), dt.timedelta(minutes=15)),
                (dt.timedelta(minutes=35), dt.timedelta(minutes=45)),
            ],
            [
                (dt.timedelta(minutes=0), dt.timedelta(minutes=10)),
                (dt.timedelta(minutes=15), dt.timedelta(minutes=35)),
                (dt.timedelta(minutes=45), dt.timedelta(minutes=60)),
            ],
        ),
        (
            [
                (dt.timedelta(minutes=45), dt.timedelta(minutes=60)),
            ],
            [
                (dt.timedelta(minutes=0), dt.timedelta(minutes=45)),
            ],
        ),
    ],
)
async def test_insert_into_redshift_activity_resumes_from_heartbeat(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    done_relative_ranges,
    expected_relative_ranges,
):
    """Test we insert partial data into a Redshift table when resuming.

    After an activity runs, heartbeats, and crashes, a follow-up activity should
    pick-up from where the first one left. This capability is critical to ensure
    long-running activities that export a lot of data will eventually finish.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    properties_data_type = "varchar"

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    done_ranges = [
        (
            (data_interval_start + done_relative_range[0]).isoformat(),
            (data_interval_start + done_relative_range[1]).isoformat(),
        )
        for done_relative_range in done_relative_ranges
    ]
    expected_ranges = [
        (
            (data_interval_start + expected_relative_range[0]),
            (data_interval_start + expected_relative_range[1]),
        )
        for expected_relative_range in expected_relative_ranges
    ]
    workflow_id = uuid.uuid4()

    fake_info = activity.Info(
        activity_id="insert-into-redshift-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="redshift-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=1,
        heartbeat_timeout=dt.timedelta(seconds=1),
        heartbeat_details=[done_ranges],
        is_local=False,
        schedule_to_close_timeout=dt.timedelta(seconds=10),
        scheduled_time=dt.datetime.now(dt.UTC),
        start_to_close_timeout=dt.timedelta(seconds=20),
        started_time=dt.datetime.now(dt.UTC),
        task_queue="test",
        task_token=b"test",
        workflow_namespace="default",
        priority=temporalio.common.Priority(priority_key=None),
    )

    activity_environment.info = fake_info
    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshift(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=expected_ranges,
        batch_export_model=batch_export_model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key="event",
        expected_duplicates_threshold=0.1,
    )


async def test_insert_into_redshift_activity_completes_range(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test we complete a full range of data into a Redshift table when resuming.

    We run two activities:
    1. First activity, up to (and including) the cutoff event.
    2. Second activity with a heartbeat detail matching the cutoff event.

    This simulates the batch export resuming from a failed execution. The full range
    should be completed (with a duplicate on the cutoff event) after both activities
    are done.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    properties_data_type = "varchar"

    events_to_export_created, _ = generate_test_data
    events_to_export_created.sort(key=operator.itemgetter("inserted_at"))

    cutoff_event = events_to_export_created[len(events_to_export_created) // 2 : len(events_to_export_created) // 2 + 1]
    assert len(cutoff_event) == 1
    cutoff_event = cutoff_event[0]
    cutoff_data_interval_end = dt.datetime.fromisoformat(cutoff_event["inserted_at"]).replace(tzinfo=dt.UTC)

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        # The extra second is because the upper range select is exclusive and
        # we want cutoff to be the last event included.
        data_interval_end=(cutoff_data_interval_end + dt.timedelta(seconds=1)).isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    done_ranges = [
        (
            data_interval_start.isoformat(),
            cutoff_data_interval_end.isoformat(),
        ),
    ]
    workflow_id = uuid.uuid4()

    fake_info = activity.Info(
        activity_id="insert-into-redshift-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="redshift-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=1,
        heartbeat_timeout=dt.timedelta(seconds=1),
        heartbeat_details=[done_ranges],
        is_local=False,
        schedule_to_close_timeout=dt.timedelta(seconds=10),
        scheduled_time=dt.datetime.now(dt.UTC),
        start_to_close_timeout=dt.timedelta(seconds=20),
        started_time=dt.datetime.now(dt.UTC),
        task_queue="test",
        task_token=b"test",
        workflow_namespace="default",
        priority=temporalio.common.Priority(priority_key=None),
    )

    activity_environment.info = fake_info

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshift(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=batch_export_model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key="event",
        expected_duplicates_threshold=0.1,
    )
