"""Test module covering the activities used for batch exporting to BigQuery."""

import uuid
import datetime as dt

import pytest
import unittest.mock

from google.cloud import bigquery

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryInsertInputs,
    bigquery_default_fields,
    insert_into_bigquery_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
    TEST_MODELS,
    TEST_TIME,
    assert_clickhouse_records_in_bigquery,
)
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

pytestmark = [
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
    pytest.mark.asyncio,
    pytest.mark.django_db,
]

EXPECTED_PERSONS_BATCH_EXPORT_FIELDS = [
    "team_id",
    "distinct_id",
    "person_id",
    "properties",
    "person_version",
    "person_distinct_id_version",
    "created_at",
    "_inserted_at",
    "is_deleted",
]


async def _run_activity(
    activity_environment,
    bigquery_client,
    clickhouse_client,
    bigquery_config,
    team,
    data_interval_start,
    data_interval_end,
    table_id: str,
    dataset_id: str,
    use_json_type: bool = False,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    expected_fields=None,
    expect_duplicates: bool = False,
    min_ingested_timestamp: dt.datetime = TEST_TIME,
):
    """Helper function to run BigQuery main activity and assert records are exported."""
    insert_inputs = BigQueryInsertInputs(
        team_id=team.pk,
        table_id=table_id,
        dataset_id=dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        use_json_type=use_json_type,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        batch_export_id=str(uuid.uuid4()),
        **bigquery_config,
    )

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
            destination_default_fields=bigquery_default_fields(),
        ),
    )
    result = await activity_environment.run(insert_into_bigquery_activity_from_stage, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=dataset_id,
        team_id=team.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        exclude_events=exclude_events,
        include_events=include_events,
        batch_export_model=batch_export_model or batch_export_schema,
        use_json_type=use_json_type,
        min_ingested_timestamp=min_ingested_timestamp,
        sort_key=sort_key,
        expected_fields=expected_fields,
        expect_duplicates=expect_duplicates,
    )

    return result


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "test_person_properties",
    [
        {
            "utm_medium": "referral",
            "$initial_os": "Linux",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity` function inserts data into a BigQuery table.

    We use the `generate_test_data` fixture function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the `team_id` of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's `exclude_events`.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        use_json_type=use_json_type,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        bigquery_config=bigquery_config,
        sort_key=sort_key,
    )


@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="sessions", schema=None),
    ],
)
async def test_insert_into_bigquery_activity_from_stage_inserts_sessions_data_into_bigquery_table(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity_from_stage` function inserts sessions data into a BigQuery table.

    This test is the same as the previous one, but we require non-messed up properties to create the
    test session data, so we isolate this model in its own test.

    We use the `generate_test_data` fixture function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the `team_id` of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's `exclude_events`.
    """
    batch_export_model = model
    sort_key = "session_id"

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        use_json_type=use_json_type,
        batch_export_model=batch_export_model,
        bigquery_config=bigquery_config,
        sort_key=sort_key,
    )


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(
            name="events",
            schema=None,
            filters=[
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
                {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
            ],
        ),
    ],
)
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "test_person_properties",
    [
        {
            "utm_medium": "referral",
            "$initial_os": "Linux",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
async def test_insert_into_bigquery_activity_from_stage_inserts_data_into_bigquery_table_with_property_filters(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity_from_stage` function inserts data into a BigQuery table.

    This test exclusively covers a model with property filters as property filters require
    a valid JSON. And the other test uses an invalid JSON due to unpaired surrogates.

    We use the `generate_test_data` fixture function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the `team_id` of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's `exclude_events`.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        include_events=None,
        use_json_type=use_json_type,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        bigquery_config=bigquery_config,
        sort_key="event",
    )


@pytest.mark.parametrize("use_json_type", [True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_bigquery_activity_from_stage_inserts_data_into_bigquery_table_without_query_permissions(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity_from_stage` function inserts data into a BigQuery table.

    For this test we mock the `check_for_query_permissions_on_table` method to assert the
    behavior of the activity function when lacking query permissions in BigQuery.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons":
        pytest.skip("Unnecessary test case as person batch export requires query permissions")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    with (
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.BigQueryClient.check_for_query_permissions",
            return_value=False,
        ) as mocked_check,
    ):
        await _run_activity(
            activity_environment,
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            team=ateam,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            include_events=None,
            use_json_type=use_json_type,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            bigquery_config=bigquery_config,
            sort_key="event",
        )

        mocked_check.assert_called_once()


async def test_insert_into_bigquery_activity_from_stage_merges_persons_data_in_follow_up_runs(
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
    """Test that the `insert_into_bigquery_activity_from_stage` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in BigQuery after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)
    table_id = f"test_insert_activity_mutability_table_persons_{ateam.pk}"

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
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

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
        sort_key="person_id",
    )


async def test_insert_into_bigquery_activity_from_stage_merges_sessions_data_in_follow_up_runs(
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
    """Test that the `insert_into_bigquery_activity_from_stage` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the raw_sessions table for the one session exported in the first
    run of the activity. We expect the new entries to have replaced the old ones in BigQuery after
    the second run with the same time range.
    """
    model = BatchExportModel(name="sessions", schema=None)
    table_id = f"test_insert_activity_mutability_table_sessions_{ateam.pk}"

    result = await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
        sort_key="session_id",
    )

    assert result.records_completed == 1
    assert result.error is None

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

    result = await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
        sort_key="session_id",
    )

    assert result.records_completed == 1
    assert result.error is None

    query_job = bigquery_client.query(f"SELECT * FROM {bigquery_dataset.dataset_id}.{table_id}")
    result = query_job.result()
    rows = list(result)
    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0]["session_id"] == new_event_properties["$session_id"]
    assert rows[0]["end_timestamp"] == dt.datetime.fromisoformat(new_event["timestamp"]).replace(tzinfo=dt.UTC)


def drop_column_from_bigquery_table(
    bigquery_client: bigquery.Client, dataset_id: str, table_id: str, column_name: str
) -> None:
    """Drop a column from a BigQuery table."""

    query_job = bigquery_client.query(f"ALTER TABLE {dataset_id}.{table_id} DROP COLUMN {column_name}")
    _ = query_job.result()


async def test_insert_into_bigquery_activity_from_stage_handles_person_schema_changes(
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
    """Test that the `insert_into_bigquery_activity_from_stage` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)
    table_id = f"test_insert_activity_migration_table_{ateam.pk}"

    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
        sort_key="person_id",
    )

    # drop the created_at column from the BigQuery table
    drop_column_from_bigquery_table(
        bigquery_client=bigquery_client,
        dataset_id=bigquery_dataset.dataset_id,
        table_id=table_id,
        column_name="created_at",
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

    # this time we don't expected there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]
    await _run_activity(
        activity_environment,
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        bigquery_config=bigquery_config,
        sort_key="person_id",
        expected_fields=expected_fields,
    )
