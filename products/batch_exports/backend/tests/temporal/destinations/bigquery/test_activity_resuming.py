"""Tests covering resuming from heartbeat functionality for BigQuery activity.

NOTE: Resuming from heartbeats is only supported when not using an internal stage
(i.e. `team_id` present in `settings.BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS`). This
test module can be removed once all BigQuery batch exports have been moved to using
`insert_into_bigquery_from_stage`.
"""

import uuid
import datetime as dt
import operator
import dataclasses

import pytest
import unittest.mock

from temporalio import activity
from temporalio.common import Priority

from posthog.batch_exports.service import BatchExportModel

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryHeartbeatDetails,
    BigQueryInsertInputs,
    insert_into_bigquery_activity,
)
from products.batch_exports.backend.temporal.spmc import RecordBatchTaskError
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
    assert_clickhouse_records_in_bigquery,
)
from products.batch_exports.backend.tests.temporal.utils import FlakyClickHouseClient

pytestmark = [
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
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
async def test_insert_into_bigquery_activity_resumes_from_heartbeat(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    done_relative_ranges,
    expected_relative_ranges,
):
    """Test we insert partial data into a BigQuery table when resuming.

    After an activity runs, heartbeats, and crashes, a follow-up activity should
    pick-up from where the first one left. This capability is critical to ensure
    long-running activities that export a lot of data will eventually finish.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    now = dt.datetime.now(tz=dt.UTC)
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
        activity_id="insert-into-bigquery-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="bigquery-export",
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
        priority=Priority(priority_key=None),
    )

    activity_environment.info = fake_info
    table_id = f"test_insert_activity_table_{ateam.pk}"

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=expected_ranges,
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
    )


async def test_insert_into_bigquery_activity_completes_range(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test we complete a full range of data into a BigQuery table when resuming.

    We run two activities:
    1. First activity, up to (and including) the cutoff event.
    2. Second activity with a heartbeat detail matching the cutoff event.

    This simulates the batch export resuming from a failed execution. The full range
    should be completed (with a duplicate on the cutoff event) after both activities
    are done.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    now = dt.datetime.now(tz=dt.UTC)

    events_to_export_created, _ = generate_test_data
    events_to_export_created.sort(key=operator.itemgetter("inserted_at"))

    cutoff_event = events_to_export_created[len(events_to_export_created) // 2 : len(events_to_export_created) // 2 + 1]
    assert len(cutoff_event) == 1
    cutoff_event = cutoff_event[0]
    cutoff_data_interval_end = dt.datetime.fromisoformat(cutoff_event["inserted_at"]).replace(tzinfo=dt.UTC)

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        # The extra second is because the upper range select is exclusive and
        # we want cutoff to be the last event included.
        data_interval_end=(cutoff_data_interval_end + dt.timedelta(seconds=1)).isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    done_ranges = [
        (
            data_interval_start.isoformat(),
            cutoff_data_interval_end.isoformat(),
        ),
    ]
    workflow_id = uuid.uuid4()

    fake_info = activity.Info(
        activity_id="insert-into-bigquery-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="bigquery-export",
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
        priority=Priority(priority_key=None),
    )

    activity_environment.info = fake_info

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
        expect_duplicates=True,
    )


async def test_insert_into_bigquery_activity_completes_range_when_there_is_a_failure(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that if the insert_into_bigquery_activity activity fails, it can resume from a heartbeat.

    We simulate a failure in the SPMC producer halfway through streaming records, then resume from the heartbeat.
    We're particularly interested in ensuring all records are exported into the final BigQuery table.
    """

    batch_export_model = BatchExportModel(name="events", schema=None)
    now = dt.datetime.now(tz=dt.UTC)
    fail_after_records = 200

    heartbeat_details: list[BigQueryHeartbeatDetails] = []

    def track_heartbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        bigquery_details = BigQueryHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(bigquery_details)

    activity_environment.on_heartbeat = track_heartbeat_details

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    with unittest.mock.patch(
        "posthog.temporal.common.clickhouse.ClickHouseClient",
        lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
    ):
        # we expect this to raise an exception
        with pytest.raises(RecordBatchTaskError):
            await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) > 0
    assert detail.records_completed == fail_after_records

    # now we resume from the heartbeat
    previous_info = dataclasses.asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )

    activity_environment.info = new_info

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    # records_completed is actually larger than num_expected_records because of duplicates
    # assert detail.records_completed == num_expected_records

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
        expect_duplicates=True,
    )
