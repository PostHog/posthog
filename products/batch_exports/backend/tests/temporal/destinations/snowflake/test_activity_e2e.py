"""
Test the Snowflake Insert Activity.

Note: This module uses a real Snowflake connection.
"""

import dataclasses
import datetime as dt
import os
import unittest.mock
import uuid

import pytest
from django.test import override_settings
from temporalio import activity

from posthog.batch_exports.service import (
    BatchExportModel,
    BatchExportSchema,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeHeartbeatDetails,
    SnowflakeInsertInputs,
    insert_into_snowflake_activity,
    insert_into_snowflake_activity_from_stage,
    snowflake_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchTaskError,
)
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import (
    EXPECTED_PERSONS_BATCH_EXPORT_FIELDS,
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
    TEST_MODELS,
    assert_clickhouse_records_in_snowflake,
)
from products.batch_exports.backend.tests.temporal.utils import (
    FlakyClickHouseClient,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
    # While we migrate to the new workflow, we need to test both new and old activities
    pytest.mark.parametrize("use_internal_stage", [False, True]),
]


async def _run_activity(
    activity_environment,
    snowflake_cursor,
    clickhouse_client,
    snowflake_config,
    team,
    data_interval_start,
    data_interval_end,
    table_name: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events=None,
    sort_key: str = "event",
    expected_fields=None,
    expect_duplicates: bool = False,
    primary_key=None,
    use_internal_stage: bool = False,
):
    """Helper function to run insert_into_snowflake_activity and assert records in Snowflake"""
    insert_inputs = SnowflakeInsertInputs(
        team_id=team.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        batch_export_id=str(uuid.uuid4()),
        **snowflake_config,
    )

    if use_internal_stage:
        assert insert_inputs.batch_export_id is not None
        # we first need to run the insert_into_internal_stage_activity so that we have data to export
        await activity_environment.run(
            insert_into_internal_stage_activity,
            BatchExportInsertIntoInternalStageInputs(
                team_id=insert_inputs.team_id,
                batch_export_id=insert_inputs.batch_export_id,
                data_interval_start=insert_inputs.data_interval_start,
                data_interval_end=insert_inputs.data_interval_end,
                exclude_events=insert_inputs.exclude_events,
                include_events=None,
                run_id=None,
                backfill_details=None,
                batch_export_model=insert_inputs.batch_export_model,
                batch_export_schema=insert_inputs.batch_export_schema,
                destination_default_fields=snowflake_default_fields(),
            ),
        )
        await activity_environment.run(insert_into_snowflake_activity_from_stage, insert_inputs)
    else:
        await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=team.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=batch_export_model or batch_export_schema,
        sort_key=sort_key,
        expected_fields=expected_fields,
        expect_duplicates=expect_duplicates,
        primary_key=primary_key,
    )


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_snowflake_activity_inserts_data_into_snowflake_table(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the insert_into_snowflake_activity function inserts data into a Snowflake table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_snowflake function to check
    that they appear in the expected Snowflake table. This function runs against a real Snowflake
    instance, so the environment should be populated with the necessary credentials.
    """
    if isinstance(model, BatchExportModel) and model.name != "events" and exclude_events is not None:
        pytest.skip("Unnecessary test case as batch export model is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    table_name = f"test_insert_activity_table_{ateam.pk}"

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
        sort_key=sort_key,
        use_internal_stage=use_internal_stage,
    )


async def test_insert_into_snowflake_activity_merges_persons_data_in_follow_up_runs(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` merges new versions of person rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in Snowflake after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)
    table_name = f"test_insert_activity_table_mutable_persons_{ateam.pk}"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
    )

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
    )


async def test_insert_into_snowflake_activity_merges_sessions_data_in_follow_up_runs(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` merges new versions of sessions rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the raw_sessions table for the one session exported in the first
    run of the activity. We expect the new entries to have replaced the old ones in Snowflake after
    the second run with the same time range.
    """
    model = BatchExportModel(name="sessions", schema=None)
    table_name = f"test_insert_activity_table_mutable_sessions_{ateam.pk}"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="session_id",
        use_internal_stage=use_internal_stage,
    )

    events_to_export_created, _ = generate_test_data
    event = events_to_export_created[0]

    new_data_interval_start, new_data_interval_end = (
        data_interval_start + dt.timedelta(hours=1),
        data_interval_end + dt.timedelta(hours=1),
    )

    new_events, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=new_data_interval_start,
        end_time=new_data_interval_end,
        count=1,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties=event["properties"],
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        event_name=event["event"],
        table="sharded_events",
        insert_sessions=True,
    )

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="session_id",
        use_internal_stage=use_internal_stage,
    )

    snowflake_cursor.execute(f'SELECT "session_id", "end_timestamp" FROM "{table_name}"')
    rows = list(snowflake_cursor.fetchall())
    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0][0] == new_event_properties["$session_id"]
    assert rows[0][1] == dt.datetime.fromisoformat(new_event["timestamp"])


async def test_insert_into_snowflake_activity_removes_internal_stage_files(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    garbage_jsonl_file,
):
    """Test that the `insert_into_snowflake_activity` removes internal stage files.

    This test requires some setup steps:
    1. We do a first run of the activity to create the export table. Since we
        haven't added any garbage, this should work normally.
    2. Truncate the table to avoid duplicate data once we re-run the activity.
    3. PUT a file with garbage data into the table internal stage.

    Once we run the activity a second time, it should first clear up the garbage
    file and not fail the COPY. After this second execution is done, and besides
    checking this second run worked and exported data, we also check that no files
    are present in the table's internal stage.
    """
    model = BatchExportModel(name="events", schema=None)
    table_name = f"test_insert_activity_table_remove_{ateam.pk}"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="event",
        use_internal_stage=use_internal_stage,
    )

    snowflake_cursor.execute(f'TRUNCATE TABLE "{table_name}"')

    data_interval_end_str = data_interval_end.strftime("%Y-%m-%d_%H-%M-%S")

    put_query = f"""
    PUT file://{garbage_jsonl_file} '@%"{table_name}"/{data_interval_end_str}'
    """
    snowflake_cursor.execute(put_query)

    list_query = f"""
    LIST '@%"{table_name}"'
    """
    snowflake_cursor.execute(list_query)
    rows = snowflake_cursor.fetchall()
    columns = {index: metadata.name for index, metadata in enumerate(snowflake_cursor.description)}
    stage_files = [{columns[index]: row[index] for index in columns.keys()} for row in rows]
    assert len(stage_files) == 1
    assert stage_files[0]["name"] == f"{data_interval_end_str}/{os.path.basename(garbage_jsonl_file)}.gz"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="event",
        use_internal_stage=use_internal_stage,
    )

    snowflake_cursor.execute(list_query)
    rows = snowflake_cursor.fetchall()
    assert len(rows) == 0


async def test_insert_into_snowflake_activity_heartbeats(
    use_internal_stage,
    clickhouse_client,
    ateam,
    snowflake_batch_export,
    snowflake_cursor,
    snowflake_config,
    activity_environment,
):
    """Test that the insert_into_snowflake_activity activity sends heartbeats.

    We use a function that runs on_heartbeat to check and track the heartbeat contents.
    """
    data_interval_end = dt.datetime.now(dt.UTC)
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    n_expected_files = 3

    for n_expected_file in range(1, n_expected_files + 1):
        part_inserted_at = data_interval_end - snowflake_batch_export.interval_time_delta / n_expected_file

        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=1,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            inserted_at=part_inserted_at,
            event_name=f"test-event-{n_expected_file}-{{i}}",
        )

    captured_details = []

    def capture_heartbeat_details(*details):
        """A function to track what we heartbeat."""
        nonlocal captured_details

        captured_details.append(details)

    activity_environment.on_heartbeat = capture_heartbeat_details

    table_name = f"test_insert_activity_table_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_id=str(uuid.uuid4()),
        **snowflake_config,
    )

    with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=0):
        if use_internal_stage:
            assert insert_inputs.batch_export_id is not None
            await activity_environment.run(
                insert_into_internal_stage_activity,
                BatchExportInsertIntoInternalStageInputs(
                    team_id=insert_inputs.team_id,
                    batch_export_id=insert_inputs.batch_export_id,
                    data_interval_start=insert_inputs.data_interval_start,
                    data_interval_end=insert_inputs.data_interval_end,
                    exclude_events=insert_inputs.exclude_events,
                    include_events=None,
                    run_id=None,
                    backfill_details=None,
                    batch_export_model=insert_inputs.batch_export_model,
                    batch_export_schema=insert_inputs.batch_export_schema,
                    destination_default_fields=snowflake_default_fields(),
                ),
            )
            await activity_environment.run(insert_into_snowflake_activity_from_stage, insert_inputs)
        else:
            await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    # It's not guaranteed we will heartbeat right after every file.
    assert len(captured_details) > 0

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        sort_key="event",
    )


async def test_insert_into_snowflake_activity_handles_person_schema_changes(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)
    table_name = f"test_insert_activity_migration_table_{ateam.pk}"

    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
    )

    # Drop the created_at column from the Snowflake table
    snowflake_cursor.execute(f'ALTER TABLE "{table_name}" DROP COLUMN "created_at"')

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    # This time we don't expect there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]
    await _run_activity(
        activity_environment=activity_environment,
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        snowflake_config=snowflake_config,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        table_name=table_name,
        batch_export_model=model,
        sort_key="person_id",
        expected_fields=expected_fields,
        use_internal_stage=use_internal_stage,
    )


@pytest.mark.parametrize(
    "model", [BatchExportModel(name="events", schema=None), BatchExportModel(name="persons", schema=None)]
)
async def test_insert_into_snowflake_activity_completes_range_when_there_is_a_failure(
    use_internal_stage,
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    model,
):
    """Test that when there is a failure, the next run completes successfully.

    For the old insert_into_snowflake_activity we can resume from a failure using heartbeat details.

    The new insert_into_snowflake_activity_from_stage doesn't support resuming from heartbeats, so we just want to
    ensure that the next run completes successfully.
    """
    table_name = f"test_insert_activity_table_{ateam.pk}"

    events_to_create, persons_to_create = generate_test_data
    total_records = len(persons_to_create) if model.name == "persons" else len(events_to_create)
    # fail halfway through
    fail_after_records = total_records // 2

    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        batch_export_id=str(uuid.uuid4()),
        **snowflake_config,
    )

    heartbeat_details: list[SnowflakeHeartbeatDetails] = []

    def track_heartbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        snowflake_details = SnowflakeHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(snowflake_details)

    if use_internal_stage:
        assert insert_inputs.batch_export_id is not None
        await activity_environment.run(
            insert_into_internal_stage_activity,
            BatchExportInsertIntoInternalStageInputs(
                team_id=insert_inputs.team_id,
                batch_export_id=insert_inputs.batch_export_id,
                data_interval_start=insert_inputs.data_interval_start,
                data_interval_end=insert_inputs.data_interval_end,
                exclude_events=insert_inputs.exclude_events,
                include_events=None,
                run_id=None,
                backfill_details=None,
                batch_export_model=insert_inputs.batch_export_model,
                batch_export_schema=insert_inputs.batch_export_schema,
                destination_default_fields=snowflake_default_fields(),
            ),
        )
        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.ProducerFromInternalStage.start",
            side_effect=ValueError("A useful error message"),
        ):
            # We expect this to raise an exception
            with pytest.raises(ValueError):
                await activity_environment.run(insert_into_snowflake_activity_from_stage, insert_inputs)

        # retrying should succeed
        await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    else:
        activity_environment.on_heartbeat = track_heartbeat_details

        with unittest.mock.patch(
            "posthog.temporal.common.clickhouse.ClickHouseClient",
            lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
        ):
            # We expect this to raise an exception
            with pytest.raises(RecordBatchTaskError):
                await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

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

        await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

        assert len(heartbeat_details) > 0
        detail = heartbeat_details[-1]
        assert len(detail.done_ranges) == 1
        assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    # Verify all the data for the whole range was exported correctly
    sort_key = "event" if model.name == "events" else "person_id"
    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        sort_key=sort_key,
        batch_export_model=model,
        expect_duplicates=True,
        primary_key=["uuid"] if model.name == "events" else ["distinct_id", "person_id"],
    )
