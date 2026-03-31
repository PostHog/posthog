import uuid
import urllib.parse

import pytest

import aiohttp

from products.batch_exports.backend.service import BatchExportInsertInputs, BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal.destinations.workflows_batch_export import (
    BadRequest,
    NotFound,
    WorkflowsInsertInputs,
    insert_into_workflows_activity_from_stage,
    workflows_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.workflows.utils import (
    assert_clickhouse_records_were_handled,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


async def _run_activity(
    activity_environment,
    server,
    handler,
    hog_function_id,
    clickhouse_client,
    team,
    data_interval_start,
    data_interval_end,
    sort_key: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    expected_fields=None,
    expect_duplicates: bool = False,
):
    """Helper function to run Workflows main activity and assert records exported."""
    batch_export_id = str(uuid.uuid4())
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
        batch_export_id=batch_export_id,
    )
    workflows_inputs = WorkflowsInsertInputs(
        batch_export=batch_export_inputs,
        url=urllib.parse.urlunsplit((server.scheme, f"{server.host}:{server.port}", "/", "", "")),
        hog_function_id=hog_function_id,
    )

    assert workflows_inputs.batch_export.batch_export_id is not None
    await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=workflows_inputs.batch_export.team_id,
            batch_export_id=workflows_inputs.batch_export.batch_export_id,
            data_interval_start=workflows_inputs.batch_export.data_interval_start,
            data_interval_end=workflows_inputs.batch_export.data_interval_end,
            exclude_events=workflows_inputs.batch_export.exclude_events,
            include_events=None,
            run_id=None,
            backfill_details=None,
            num_partitions=1,
            is_workflows=True,
            batch_export_model=workflows_inputs.batch_export.batch_export_model,
            batch_export_schema=workflows_inputs.batch_export.batch_export_schema,
            destination_default_fields=workflows_default_fields(batch_export_id),
        ),
    )
    result = await activity_environment.run(insert_into_workflows_activity_from_stage, workflows_inputs)

    await assert_clickhouse_records_were_handled(
        clickhouse_client=clickhouse_client,
        handler=handler,
        hog_function_id=hog_function_id,
        date_ranges=[(data_interval_start, data_interval_end)],
        team_id=team.pk,
        batch_export_model=batch_export_model or batch_export_schema,
        exclude_events=exclude_events,
        sort_key=sort_key,
        expected_fields=expected_fields,
        batch_export_id=batch_export_id,
    )

    return result


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_insert_into_workflows_activity_from_stage_posts_data_to_server(
    clickhouse_client,
    activity_environment,
    exclude_events,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    ateam,
    server,
    path,
    handler,
    hog_function_id,
):
    """Assert basic activity behavior.

    This configures the activity to POST requests to an aiohttp test server, configured
    in the server fixture.
    """
    model = BatchExportModel(name="events", schema=None)

    await _run_activity(
        activity_environment,
        server=server,
        handler=handler,
        hog_function_id=hog_function_id,
        clickhouse_client=clickhouse_client,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key="event",
    )


@pytest.mark.parametrize("error", [404, 400], indirect=True)
async def test_insert_into_workflows_activity_from_stage_fails_on_non_retryable_errors(
    clickhouse_client,
    activity_environment,
    exclude_events,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    ateam,
    server,
    path,
    handler,
    hog_function_id,
    error,
):
    """Assert the activity immediately fails on non-retryable error codes."""
    model = BatchExportModel(name="events", schema=None)

    if error == 404:
        expected: type[aiohttp.ClientResponseError] = NotFound
    else:
        expected = BadRequest

    with pytest.raises(expected):
        await _run_activity(
            activity_environment,
            server=server,
            handler=handler,
            hog_function_id=hog_function_id,
            clickhouse_client=clickhouse_client,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            batch_export_model=model,
            sort_key="event",
        )

    assert len(handler.error_data) == 1  # First request failed...
    assert not len(handler.data)  # And it wasn't retried


@pytest.mark.parametrize("error", [429, 500], indirect=True)
async def test_insert_into_workflows_activity_from_stage_retries_on_retryable_errors(
    clickhouse_client,
    activity_environment,
    exclude_events,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    ateam,
    server,
    path,
    handler,
    hog_function_id,
    error,
):
    """Assert the activity retries requests on retryable error codes."""
    model = BatchExportModel(name="events", schema=None)

    await _run_activity(
        activity_environment,
        server=server,
        handler=handler,
        hog_function_id=hog_function_id,
        clickhouse_client=clickhouse_client,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key="event",
    )

    assert len(handler.error_data) == 1  # First request failed...
    assert handler.error_data[0] in handler.data  # And should have been retried


async def test_insert_into_workflows_activity_from_stage_fails_with_empty_url(
    clickhouse_client,
    activity_environment,
    exclude_events,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    ateam,
    server,
    path,
    handler,
    hog_function_id,
    error,
):
    """Assert activity fails when an empty URL is passed."""
    model = BatchExportModel(name="events", schema=None)

    batch_export_id = str(uuid.uuid4())
    batch_export_inputs = BatchExportInsertInputs(
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        run_id=None,
        backfill_details=None,
        is_backfill=False,
        batch_export_model=model,
        batch_export_id=batch_export_id,
    )
    workflows_inputs = WorkflowsInsertInputs(
        batch_export=batch_export_inputs,
        url="",
        hog_function_id=hog_function_id,
    )

    await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=workflows_inputs.batch_export.team_id,
            batch_export_id=batch_export_id,
            data_interval_start=workflows_inputs.batch_export.data_interval_start,
            data_interval_end=workflows_inputs.batch_export.data_interval_end,
            exclude_events=workflows_inputs.batch_export.exclude_events,
            is_workflows=True,
            batch_export_model=workflows_inputs.batch_export.batch_export_model,
            destination_default_fields=workflows_default_fields(batch_export_id),
        ),
    )

    with pytest.raises(ValueError):
        await activity_environment.run(insert_into_workflows_activity_from_stage, workflows_inputs)
