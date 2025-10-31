import uuid

import pytest

from django.test import override_settings

from psycopg import sql

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    PostgresInsertInputs,
    insert_into_postgres_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.postgres.utils import (
    EXPECTED_PERSONS_BATCH_EXPORT_FIELDS,
    TEST_MODELS,
    assert_clickhouse_records_in_postgres,
)
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_postgres_activity_inserts_data_into_postgres_table(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the insert_into_postgres_activity function inserts data into a PostgreSQL table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_postgres function to check
    that they appear in the expected PostgreSQL table. This function utilizes the local
    development postgres instance for testing. But we setup and manage our own database
    to avoid conflicting with PostHog itself.
    """
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name="test_table",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name="test_table",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
    )


@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
            "newline": "\n",
            "unicode_null": "\u0000",
            "invalid_unicode": "\\u0000'",  # this has given us issues in the past
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
async def test_insert_into_postgres_activity_handles_problematic_json(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    exclude_events,
    model: BatchExportModel,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Sometimes users send us invalid JSON. We want to test that we handle this gracefully.

    We only use the event model here since custom models with expressions such as JSONExtractString will still fail, as
    ClickHouse is not able to parse invalid JSON. There's not much we can do about this case.
    """

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model = model

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name="test_table",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    sort_key = "event"
    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name="test_table",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
    )


async def test_insert_into_postgres_activity_merges_persons_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_postgres_activity` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in PostgreSQL after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)
    table_name = f"test_insert_activity_mutability_table_persons_{ateam.pk}"

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **postgres_config,
    )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
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

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )


async def test_insert_into_postgres_activity_merges_sessions_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_postgres_activity` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the sessions table after an initial run. We expect the new
    entry to have replaced the old ones in PostgreSQL after the second run.
    """
    import datetime as dt

    from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

    model = BatchExportModel(name="sessions", schema=None)
    table_name = f"test_insert_activity_mutability_table_sessions_{ateam.pk}"

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **postgres_config,
    )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
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

    insert_inputs.data_interval_start = new_data_interval_start.isoformat()
    insert_inputs.data_interval_end = new_data_interval_end.isoformat()

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
    )

    rows = []
    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(postgres_config["schema"], table_name)))

        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            rows.append(event)

    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0]["session_id"] == new_event_properties["$session_id"]
    assert rows[0]["end_timestamp"] == dt.datetime.fromisoformat(new_event["timestamp"]).replace(tzinfo=dt.UTC)


@pytest.fixture
async def persons_table_without_primary_key(postgres_connection, postgres_config, table_name):
    """Managed a table for a persons batch export without a primary key."""
    self_managed_table_name = table_name + f"_self_managed_{uuid.uuid4().hex}"

    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    """
                    CREATE TABLE {table} (
                        team_id BIGINT,
                        distinct_id TEXT,
                        person_id TEXT,
                        properties JSONB,
                        person_distinct_id_version BIGINT,
                        person_version BIGINT,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP,
                        is_deleted BOOLEAN
                    )
                    """
                ).format(table=sql.Identifier(postgres_config["schema"], self_managed_table_name))
            )

    yield self_managed_table_name

    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {table}").format(
                    table=sql.Identifier(postgres_config["schema"], self_managed_table_name)
                )
            )


@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_insert_into_postgres_activity_inserts_fails_on_missing_primary_key(
    activity_environment,
    postgres_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
    ateam,
    generate_test_data,
    persons_table_without_primary_key,
):
    """Test the insert_into_postgres_activity function fails when missing a primary key.

    We use a self-managed, previously created postgresql table to export persons data to.
    Since this table does not have a primary key, the merge query should fail.

    This error should only occur if the table is created outside the batch export.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=persons_table_without_primary_key,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        result = await activity_environment.run(insert_into_postgres_activity, insert_inputs)
        assert result.error is not None
        assert result.error.type == "MissingPrimaryKeyError"
        assert result.error.message.startswith("An operation could not be completed as")


async def test_insert_into_postgres_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_postgres_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **postgres_config,
    )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )

    # Drop the created_at column from the PostgreSQL table
    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN created_at").format(
                    table=sql.Identifier(postgres_config["schema"], f"test_insert_activity_migration_table__{ateam.pk}")
                )
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

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    # This time we don't expect there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
        expected_fields=expected_fields,
    )
