import uuid
import datetime as dt

import pytest

from psycopg import sql

from posthog.batch_exports.service import BatchExportInsertInputs, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ConnectionParameters,
    RedshiftInsertInputs,
    TableParameters,
    insert_into_redshift_activity,
    insert_into_redshift_activity_from_stage,
    redshift_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import (
    MISSING_REQUIRED_ENV_VARS,
    TEST_MODELS,
    assert_clickhouse_records_in_redshift,
)
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    # While we migrate to the new workflow, we need to test both new and old activities
    pytest.mark.parametrize("use_internal_stage", [False, True]),
]


async def _run_activity(
    activity_environment,
    redshift_connection,
    clickhouse_client,
    redshift_config,
    team,
    data_interval_start,
    data_interval_end,
    table_name: str,
    properties_data_type: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    expected_fields=None,
    expect_duplicates: bool = False,
    use_internal_stage: bool = False,
    extra_fields=None,
):
    """Helper function to run Redshift main activity and assert records are exported.

    This function executes either `insert_into_redshift_activity`, or
    `insert_into_internal_stage_activity` and `insert_into_redshift_activity_from_stage`
    depending on the value of `use_internal_stage`.

    This allows using a single function to test both versions of the pipeline.
    """
    batch_export_inputs = BatchExportInsertInputs(
        team_id=team.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        run_id=None,
        backfill_details=None,
        is_backfill=False,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        batch_export_id=str(uuid.uuid4()),
        destination_default_fields=redshift_default_fields(),
    )
    connection_parameters = ConnectionParameters(
        user=redshift_config["user"],
        password=redshift_config["password"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        database=redshift_config["database"],
    )
    table_parameters = TableParameters(
        schema_name=redshift_config["schema"],
        name=table_name,
        properties_data_type=properties_data_type,
    )

    insert_inputs = RedshiftInsertInputs(
        batch_export=batch_export_inputs,
        connection=connection_parameters,
        table=table_parameters,
    )

    if use_internal_stage:
        assert insert_inputs.batch_export.batch_export_id is not None
        # we first need to run the insert_into_internal_stage_activity so that we have data to export
        await activity_environment.run(
            insert_into_internal_stage_activity,
            BatchExportInsertIntoInternalStageInputs(
                team_id=insert_inputs.batch_export.team_id,
                batch_export_id=insert_inputs.batch_export.batch_export_id,
                data_interval_start=insert_inputs.batch_export.data_interval_start,
                data_interval_end=insert_inputs.batch_export.data_interval_end,
                exclude_events=insert_inputs.batch_export.exclude_events,
                include_events=None,
                run_id=None,
                backfill_details=None,
                batch_export_model=insert_inputs.batch_export.batch_export_model,
                batch_export_schema=insert_inputs.batch_export.batch_export_schema,
                destination_default_fields=redshift_default_fields(),
            ),
        )
        result = await activity_environment.run(insert_into_redshift_activity_from_stage, insert_inputs)
    else:
        result = await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshift(
        redshift_connection=redshift_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=team.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=batch_export_model or batch_export_schema,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key=sort_key,
        expected_fields=expected_fields,
        extra_fields=extra_fields,
    )

    return result


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("properties_data_type", ["super", "varchar"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_redshift_activity_inserts_data_into_redshift_table(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    properties_data_type,
    ateam,
    use_internal_stage,
):
    """Test that the insert_into_redshift_activity function inserts data into a Redshift table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_redshift function to check
    that they appear in the expected Redshift table.
    """
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and MISSING_REQUIRED_ENV_VARS
    ):
        pytest.skip(f"Batch export model {model.name} cannot be tested in PostgreSQL")

    if properties_data_type == "super" and MISSING_REQUIRED_ENV_VARS:
        pytest.skip("SUPER type is only available in Redshift")

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        event_name="test-funny-props-{i}",
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        properties={
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "whitespace": "hi\t\n\r\f\bhi",
            "nested_whitespace": {"whitespace": "hi\t\n\r\f\bhi"},
            "sequence": {"mucho_whitespace": ["hi", "hi\t\n\r\f\bhi", "hi\t\n\r\f\bhi", "hi"]},
            "multi-byte": "é",
        },
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    table_name = f"test_insert_activity_table__{ateam.pk}"

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        redshift_config=redshift_config,
        sort_key=sort_key,
        use_internal_stage=use_internal_stage,
    )


async def test_insert_into_redshift_activity_merges_persons_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
    use_internal_stage,
):
    """Test that the `insert_into_redshift_activity` merges new versions of rows.

    This unit test looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in Redshift after
    the second run.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="persons", schema=None)
    properties_data_type = "varchar"
    table_name = f"test_insert_activity_mutability_table_{ateam.pk}"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
    )

    persons_to_export_created = generate_test_persons_data
    exported_persons = {person["distinct_id"]: person["person_id"] for person in persons_to_export_created}

    new_distinct_id_to_person_id = {}
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
        new_distinct_id_to_person_id[old_person["distinct_id"]] = new_person[0]["id"]

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
    )

    rows = []
    async with psycopg_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(redshift_config["schema"], table_name)))

        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            rows.append(event)

    for row in rows:
        distinct_id = row["distinct_id"]
        inserted_person_id = row["person_id"]
        try:
            expected_person_id = new_distinct_id_to_person_id.pop(distinct_id)
        except KeyError:
            expected_person_id = exported_persons[distinct_id]

        assert inserted_person_id == expected_person_id
    assert not new_distinct_id_to_person_id, "One or more persons were not updated"


async def test_insert_into_redshift_activity_merges_sessions_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    use_internal_stage,
):
    """Test that the `insert_into_redshift_activity` merges new versions of rows.

    This unit test looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the raw_sessions table for the only row exported in a first
    run of the activity. We expect the new entry to have replaced the old one in Redshift after
    the second run.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Sessions batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="sessions", schema=None)
    properties_data_type = "varchar"
    table_name = f"test_insert_activity_mutability_table_sessions_{ateam.pk}"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
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
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="session_id",
        use_internal_stage=use_internal_stage,
    )

    rows = []
    async with psycopg_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(redshift_config["schema"], table_name)))

        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            rows.append(event)

    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1, "Previous session row still present in Redshift"
    assert (
        rows[0]["session_id"] == new_event_properties["$session_id"]
    ), "Redshift row does not match expected `session_id`"
    assert rows[0]["end_timestamp"] == dt.datetime.fromisoformat(new_event["timestamp"]).replace(
        tzinfo=dt.UTC
    ), "Redshift data was not updated with new timestamp"


async def test_insert_into_redshift_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
    use_internal_stage,
):
    """Test that the `insert_into_redshift_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="persons", schema=None)
    properties_data_type = "varchar"
    table_name = f"test_insert_activity_migration_table__{ateam.pk}"
    expected_fields = [
        "team_id",
        "distinct_id",
        "person_id",
        "properties",
        "person_version",
        "person_distinct_id_version",
        "created_at",
        "is_deleted",
    ]

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
        expected_fields=expected_fields,
    )

    # Drop the created_at column from the Redshift table
    async with psycopg_connection.transaction():
        async with psycopg_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN created_at").format(
                    table=sql.Identifier(redshift_config["schema"], f"test_insert_activity_migration_table__{ateam.pk}")
                )
            )

    persons_to_export_created = generate_test_persons_data

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
    expected_fields.pop(expected_fields.index("created_at"))

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="person_id",
        use_internal_stage=use_internal_stage,
        expected_fields=expected_fields,
    )


@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("properties_data_type", ["super"], indirect=True)
@pytest.mark.parametrize("model", [TEST_MODELS[1]])
async def test_insert_into_redshift_activity_inserts_data_with_extra_columns(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    properties_data_type,
    ateam,
    use_internal_stage,
):
    """Test data is inserted even in the presence of additional columns.

    Redshift's "MERGE" command can run in a simplified mode which performs better and
    cleans up duplicates, but this requires a matching schema. We should assert we don't
    fail when we can't use this mode.
    """
    if properties_data_type == "super" and MISSING_REQUIRED_ENV_VARS:
        pytest.skip("SUPER type is only available in Redshift")

    batch_export_model = model
    table_name = f"test_insert_activity_extra_column_table__{ateam.pk}"
    sort_key = "event"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        redshift_config=redshift_config,
        sort_key=sort_key,
        use_internal_stage=use_internal_stage,
    )

    async with psycopg_connection.transaction():
        async with psycopg_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN test INT DEFAULT NULL;").format(
                    sql.Identifier(redshift_config["schema"], table_name)
                )
            )

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        redshift_config=redshift_config,
        sort_key=sort_key,
        use_internal_stage=use_internal_stage,
        extra_fields=["test"],
    )
