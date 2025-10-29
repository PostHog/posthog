import os
import uuid
import datetime as dt

import pytest

from psycopg import sql

from posthog.batch_exports.service import BatchExportInsertInputs, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    AWSCredentials,
    ConnectionParameters,
    CopyParameters,
    RedshiftCopyActivityInputs,
    S3StageBucketParameters,
    TableParameters,
    copy_into_redshift_activity_from_stage,
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
    delete_all_from_s3_prefix,
    has_valid_credentials,
)
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        "S3_TEST_BUCKET" not in os.environ or not has_valid_credentials() or MISSING_REQUIRED_ENV_VARS,
        reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
    ),
]


@pytest.fixture(autouse=True)
async def clean_up_s3_bucket(s3_client, bucket_name, key_prefix):
    """Clean-up S3 bucket used in Redshift copy activity."""
    yield

    assert s3_client is not None

    await delete_all_from_s3_prefix(s3_client, bucket_name, key_prefix)


async def _run_activity(
    activity_environment,
    redshift_connection,
    clickhouse_client,
    redshift_config,
    team,
    data_interval_start,
    data_interval_end,
    table_name: str,
    bucket_name: str,
    bucket_region: str,
    key_prefix: str,
    credentials: AWSCredentials,
    properties_data_type: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    expected_fields=None,
    expect_duplicates: bool = False,
):
    """Helper function to run Redshift main COPY activity and assert records exported.

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

    copy_parameters = CopyParameters(
        s3_bucket=S3StageBucketParameters(
            name=bucket_name,
            region_name=bucket_region,
            credentials=credentials,
        ),
        s3_key_prefix=key_prefix,
        authorization=credentials,
    )

    copy_inputs = RedshiftCopyActivityInputs(
        batch_export=batch_export_inputs,
        connection=connection_parameters,
        table=table_parameters,
        copy=copy_parameters,
    )

    assert copy_inputs.batch_export.batch_export_id is not None
    await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=copy_inputs.batch_export.team_id,
            batch_export_id=copy_inputs.batch_export.batch_export_id,
            data_interval_start=copy_inputs.batch_export.data_interval_start,
            data_interval_end=copy_inputs.batch_export.data_interval_end,
            exclude_events=copy_inputs.batch_export.exclude_events,
            include_events=None,
            run_id=None,
            backfill_details=None,
            batch_export_model=copy_inputs.batch_export.batch_export_model,
            batch_export_schema=copy_inputs.batch_export.batch_export_schema,
            destination_default_fields=redshift_default_fields(),
        ),
    )
    result = await activity_environment.run(copy_into_redshift_activity_from_stage, copy_inputs)

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
        copy=True,
    )

    return result


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("properties_data_type", ["super", "varchar"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_copy_into_redshift_activity_inserts_data_into_redshift_table(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    bucket_name,
    bucket_region,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    properties_data_type,
    aws_credentials,
    key_prefix,
    ateam,
):
    """Test that the copy_into_redshift_activity function inserts data into a Redshift table."""
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

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

    table_name = f"test_copy_activity_table__{ateam.pk}"

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
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        redshift_config=redshift_config,
        sort_key=sort_key,
    )


async def test_copy_into_redshift_activity_merges_persons_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    bucket_name,
    bucket_region,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
    aws_credentials,
    key_prefix,
):
    """Test that the `copy_into_redshift_activity` merges new versions of rows.

    This unit test looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in Redshift after
    the second run.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="persons", schema=None)
    properties_data_type = "super"
    table_name = f"test_copy_activity_mutability_table_{ateam.pk}"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        bucket_name=bucket_name,
        credentials=aws_credentials,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        sort_key="person_id",
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
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        sort_key="person_id",
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


async def test_copy_into_redshift_activity_merges_sessions_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    bucket_name,
    bucket_region,
    aws_credentials,
    key_prefix,
):
    """Test that the `copy_into_redshift_activity` merges new versions of rows.

    This unit test looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the raw_sessions table for the only row exported in a first
    run of the activity. We expect the new entry to have replaced the old one in Redshift after
    the second run.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Sessions batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="sessions", schema=None)
    properties_data_type = "varchar"
    table_name = f"test_copy_activity_mutability_table_sessions_{ateam.pk}"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
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

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="session_id",
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


async def test_copy_into_redshift_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
    bucket_name,
    bucket_region,
    aws_credentials,
    key_prefix,
):
    """Test that the `copy_into_redshift_activity` handles changes to the
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
    table_name = f"test_copy_activity_migration_table__{ateam.pk}"
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
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="person_id",
        expected_fields=expected_fields,
    )

    # Drop the created_at column from the Redshift table
    async with psycopg_connection.transaction():
        async with psycopg_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN created_at").format(
                    table=sql.Identifier(redshift_config["schema"], f"test_copy_activity_migration_table__{ateam.pk}")
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
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix=key_prefix,
        credentials=aws_credentials,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        redshift_config=redshift_config,
        properties_data_type=properties_data_type,
        sort_key="person_id",
        expected_fields=expected_fields,
    )
