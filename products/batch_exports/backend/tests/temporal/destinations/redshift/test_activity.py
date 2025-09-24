import pytest

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    RedshiftInsertInputs,
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
):
    """Helper function to run Redshift main activity and assert records are exported.

    This function executes either `insert_into_redshift_activity`, or
    `insert_into_internal_stage_activity` and `insert_into_redshift_activity_from_stage`
    depending on the value of `use_internal_stage`.

    This allows using a single function to test both versions of the pipeline.
    """
    insert_inputs = RedshiftInsertInputs(
        team_id=team.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
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
        batch_export_model=batch_export_model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key=sort_key,
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
