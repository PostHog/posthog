import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.cleanup_property_definitions.types import (
    CleanupPropertyDefinitionsInput,
    DeleteClickHousePropertyDefinitionsInput,
    DeletePostgresPropertyDefinitionsInput,
    PreviewPropertyDefinitionsInput,
)
from posthog.temporal.cleanup_property_definitions.workflows import CleanupPropertyDefinitionsWorkflow


@pytest.mark.asyncio
async def test_cleanup_property_definitions_workflow():
    TEST_TEAM_ID = 12345
    TEST_PATTERN = "^temp_.*"
    TEST_PROPERTY_TYPE = "person"
    postgres_deleted = 0
    clickhouse_deleted = False

    @activity.defn(name="delete-property-definitions-from-postgres")
    async def delete_postgres_mocked(input: DeletePostgresPropertyDefinitionsInput) -> dict:
        nonlocal postgres_deleted
        assert input.team_id == TEST_TEAM_ID
        assert input.pattern == TEST_PATTERN
        assert input.property_type == 2  # PERSON
        postgres_deleted = 5
        return {"property_definitions_deleted": 5, "event_properties_deleted": 0}

    @activity.defn(name="delete-property-definitions-from-clickhouse")
    async def delete_clickhouse_mocked(input: DeleteClickHousePropertyDefinitionsInput) -> None:
        nonlocal clickhouse_deleted
        assert input.team_id == TEST_TEAM_ID
        assert input.pattern == TEST_PATTERN
        assert input.property_type == 2  # PERSON
        clickhouse_deleted = True

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[CleanupPropertyDefinitionsWorkflow],
            activities=[
                delete_postgres_mocked,
                delete_clickhouse_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CleanupPropertyDefinitionsWorkflow.run,
                CleanupPropertyDefinitionsInput(
                    team_id=TEST_TEAM_ID,
                    pattern=TEST_PATTERN,
                    property_type=TEST_PROPERTY_TYPE,
                    dry_run=False,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["team_id"] == TEST_TEAM_ID
    assert result["pattern"] == TEST_PATTERN
    assert result["property_type"] == TEST_PROPERTY_TYPE
    assert result["dry_run"] is False
    assert result["property_definitions_deleted"] == 5
    assert result["event_properties_deleted"] == 0
    assert postgres_deleted == 5
    assert clickhouse_deleted is True


@pytest.mark.asyncio
async def test_cleanup_property_definitions_workflow_dry_run():
    TEST_TEAM_ID = 12345
    TEST_PATTERN = "^temp_.*"
    TEST_PROPERTY_TYPE = "person"
    PREVIEW_NAMES = ["temp_prop_1", "temp_prop_2"]

    @activity.defn(name="delete-property-definitions-from-postgres")
    async def delete_postgres_mocked(input: DeletePostgresPropertyDefinitionsInput) -> dict:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="delete-property-definitions-from-clickhouse")
    async def delete_clickhouse_mocked(input: DeleteClickHousePropertyDefinitionsInput) -> None:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="preview-property-definitions")
    async def preview_mocked(input: PreviewPropertyDefinitionsInput) -> dict:
        assert input.team_id == TEST_TEAM_ID
        assert input.pattern == TEST_PATTERN
        assert input.property_type == 2  # PERSON
        return {"total_count": 2, "names": PREVIEW_NAMES, "truncated": False}

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[CleanupPropertyDefinitionsWorkflow],
            activities=[
                delete_postgres_mocked,
                delete_clickhouse_mocked,
                preview_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CleanupPropertyDefinitionsWorkflow.run,
                CleanupPropertyDefinitionsInput(
                    team_id=TEST_TEAM_ID,
                    pattern=TEST_PATTERN,
                    property_type=TEST_PROPERTY_TYPE,
                    dry_run=True,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["team_id"] == TEST_TEAM_ID
    assert result["pattern"] == TEST_PATTERN
    assert result["property_type"] == TEST_PROPERTY_TYPE
    assert result["dry_run"] is True
    assert result["property_definitions_deleted"] == 0
    assert result["preview"]["total_count"] == 2
    assert result["preview"]["names"] == PREVIEW_NAMES


@pytest.mark.asyncio
async def test_cleanup_property_definitions_workflow_no_matches():
    TEST_TEAM_ID = 12345
    TEST_PATTERN = "^nonexistent_.*"
    TEST_PROPERTY_TYPE = "event"

    @activity.defn(name="delete-property-definitions-from-postgres")
    async def delete_postgres_mocked(input: DeletePostgresPropertyDefinitionsInput) -> dict:
        return {"property_definitions_deleted": 0, "event_properties_deleted": 0}

    @activity.defn(name="delete-property-definitions-from-clickhouse")
    async def delete_clickhouse_mocked(input: DeleteClickHousePropertyDefinitionsInput) -> None:
        pass

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[CleanupPropertyDefinitionsWorkflow],
            activities=[
                delete_postgres_mocked,
                delete_clickhouse_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CleanupPropertyDefinitionsWorkflow.run,
                CleanupPropertyDefinitionsInput(
                    team_id=TEST_TEAM_ID,
                    pattern=TEST_PATTERN,
                    property_type=TEST_PROPERTY_TYPE,
                    dry_run=False,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["property_definitions_deleted"] == 0
    assert result["event_properties_deleted"] == 0


@pytest.mark.asyncio
async def test_cleanup_property_definitions_workflow_event_type_deletes_event_properties():
    TEST_TEAM_ID = 12345
    TEST_PATTERN = "^temp_.*"
    TEST_PROPERTY_TYPE = "event"

    @activity.defn(name="delete-property-definitions-from-postgres")
    async def delete_postgres_mocked(input: DeletePostgresPropertyDefinitionsInput) -> dict:
        assert input.property_type == 1  # EVENT
        return {"property_definitions_deleted": 10, "event_properties_deleted": 25}

    @activity.defn(name="delete-property-definitions-from-clickhouse")
    async def delete_clickhouse_mocked(input: DeleteClickHousePropertyDefinitionsInput) -> None:
        pass

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[CleanupPropertyDefinitionsWorkflow],
            activities=[
                delete_postgres_mocked,
                delete_clickhouse_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CleanupPropertyDefinitionsWorkflow.run,
                CleanupPropertyDefinitionsInput(
                    team_id=TEST_TEAM_ID,
                    pattern=TEST_PATTERN,
                    property_type=TEST_PROPERTY_TYPE,
                    dry_run=False,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["property_definitions_deleted"] == 10
    assert result["event_properties_deleted"] == 25


@pytest.mark.asyncio
async def test_cleanup_property_definitions_workflow_multiple_batches():
    TEST_TEAM_ID = 12345
    TEST_PATTERN = "^temp_.*"
    TEST_PROPERTY_TYPE = "event"
    BATCH_SIZE = 5000
    postgres_call_count = 0

    @activity.defn(name="delete-property-definitions-from-postgres")
    async def delete_postgres_mocked(input: DeletePostgresPropertyDefinitionsInput) -> dict:
        nonlocal postgres_call_count
        postgres_call_count += 1
        assert input.batch_size == BATCH_SIZE
        if postgres_call_count <= 2:
            return {"property_definitions_deleted": BATCH_SIZE, "event_properties_deleted": BATCH_SIZE * 2}
        return {"property_definitions_deleted": 3000, "event_properties_deleted": 6000}

    @activity.defn(name="delete-property-definitions-from-clickhouse")
    async def delete_clickhouse_mocked(input: DeleteClickHousePropertyDefinitionsInput) -> None:
        pass

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[CleanupPropertyDefinitionsWorkflow],
            activities=[
                delete_postgres_mocked,
                delete_clickhouse_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CleanupPropertyDefinitionsWorkflow.run,
                CleanupPropertyDefinitionsInput(
                    team_id=TEST_TEAM_ID,
                    pattern=TEST_PATTERN,
                    property_type=TEST_PROPERTY_TYPE,
                    dry_run=False,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert postgres_call_count == 3
    assert result["property_definitions_deleted"] == BATCH_SIZE + BATCH_SIZE + 3000
    assert result["event_properties_deleted"] == BATCH_SIZE * 2 + BATCH_SIZE * 2 + 6000


def test_cleanup_property_definitions_workflow_parse_inputs():
    result = CleanupPropertyDefinitionsWorkflow.parse_inputs(
        ['{"team_id": 12345, "pattern": "^temp_.*", "property_type": "person", "dry_run": true}']
    )
    assert result.team_id == 12345
    assert result.pattern == "^temp_.*"
    assert result.property_type == "person"
    assert result.dry_run is True

    result = CleanupPropertyDefinitionsWorkflow.parse_inputs(
        ['{"team_id": 99999, "pattern": "^foo_.*", "property_type": "event"}']
    )
    assert result.team_id == 99999
    assert result.pattern == "^foo_.*"
    assert result.property_type == "event"
    assert result.dry_run is False


def test_cleanup_property_definitions_input_rejects_invalid_regex():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Invalid regex pattern"):
        CleanupPropertyDefinitionsInput(
            team_id=123,
            pattern="[invalid(",
            property_type="person",
        )


def test_cleanup_property_definitions_input_rejects_re2_incompatible_patterns():
    from pydantic import ValidationError

    # Backreferences not supported in RE2
    with pytest.raises(ValidationError, match="backreferences"):
        CleanupPropertyDefinitionsInput(
            team_id=123,
            pattern=r"(.)\1",  # backreference
            property_type="person",
        )

    # Lookahead not supported in RE2
    with pytest.raises(ValidationError, match="lookahead/lookbehind"):
        CleanupPropertyDefinitionsInput(
            team_id=123,
            pattern=r"foo(?=bar)",  # positive lookahead
            property_type="person",
        )

    # Lookbehind not supported in RE2
    with pytest.raises(ValidationError, match="lookahead/lookbehind"):
        CleanupPropertyDefinitionsInput(
            team_id=123,
            pattern=r"(?<=foo)bar",  # positive lookbehind
            property_type="person",
        )


def test_cleanup_property_definitions_input_accepts_simple_patterns():
    # These patterns should work in both PostgreSQL and ClickHouse RE2
    valid_patterns = [
        "^temp_.*",
        "_test$",
        "foo.*bar",
        r"\d+_property",
        "prefix_[a-z]+_suffix",
        "^$",
        ".*",
    ]

    for pattern in valid_patterns:
        result = CleanupPropertyDefinitionsInput(
            team_id=123,
            pattern=pattern,
            property_type="person",
        )
        assert result.pattern == pattern
