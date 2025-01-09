from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, UTC
from typing import NamedTuple, TypedDict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from django.conf import settings
from temporalio.client import Client
from temporalio.testing import ActivityEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL
from posthog.temporal.batch_exports.squash_person_overrides import (
    MutationActivityInputs,
    SquashPersonOverridesInputs,
    SquashPersonOverridesWorkflow,
    TableActivityInputs,
    create_table,
    drop_table,
    parse_mutation_counts,
    submit_mutation,
    wait_for_mutation,
    wait_for_table,
)
from posthog.temporal.common.clickhouse import get_client


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def ensure_database_tables(clickhouse_client, django_db_setup):
    """Ensure necessary person_distinct_id_overrides table and related exist.

    This is a module scoped fixture as most if not all tests in this module require the
    person_distinct_id_overrides table in one way or another.
    """
    await clickhouse_client.execute_query(PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL())

    yield


EVENT_TIMESTAMP = datetime.fromisoformat("2020-01-02T00:00:00.123123+00:00")
LATEST_VERSION = 8


class PersonOverrideTuple(NamedTuple):
    distinct_id: str
    person_id: UUID


async def _insert_overrides(clickhouse_client, person_overrides: Mapping[int, set[PersonOverrideTuple]], version: int):
    rows = []

    for team_id, overrides in person_overrides.items():
        for override in overrides:
            values = {
                "team_id": team_id,
                "distinct_id": override.distinct_id,
                "person_id": override.person_id,
                "version": version,
            }
            rows.append(values)

    await clickhouse_client.execute_query("INSERT INTO person_distinct_id_overrides FORMAT JSONEachRow", *rows)


@pytest_asyncio.fixture
async def person_overrides_data(clickhouse_client):
    """Produce some fake person_overrides data for testing.

    We yield a dictionary of team_id to sets of PersonOverrideTuple. These dict can be
    used to make assertions on which should be the right person id of an event.
    """
    person_overrides = {
        # These numbers are all arbitrary.
        100: {PersonOverrideTuple(str(uuid4()), uuid4()) for _ in range(5)},
        200: {PersonOverrideTuple(str(uuid4()), uuid4()) for _ in range(4)},
        300: {PersonOverrideTuple(str(uuid4()), uuid4()) for _ in range(3)},
    }

    await _insert_overrides(clickhouse_client, person_overrides, version=LATEST_VERSION)

    yield person_overrides

    await clickhouse_client.execute_query("TRUNCATE TABLE person_distinct_id_overrides")


@pytest_asyncio.fixture
async def older_overrides(person_overrides_data: Mapping[int, set[PersonOverrideTuple]], clickhouse_client):
    """Generate additional person overrides that have an older version than the test data."""
    older_overrides = defaultdict(set)

    for team_id, overrides in person_overrides_data.items():
        for override in overrides:
            older_overrides[team_id].add(override._replace(person_id=uuid4()))

    await _insert_overrides(clickhouse_client, older_overrides, version=LATEST_VERSION - 1)

    yield older_overrides


@pytest_asyncio.fixture
async def newer_overrides(person_overrides_data: Mapping[int, set[PersonOverrideTuple]], clickhouse_client):
    """Generate additional person overrides that have a newer version than the test data."""
    newer_overrides = defaultdict(set)

    for team_id, overrides in person_overrides_data.items():
        for override in overrides:
            newer_overrides[team_id].add(override._replace(person_id=uuid4()))

    await _insert_overrides(clickhouse_client, newer_overrides, version=LATEST_VERSION + 1)

    yield newer_overrides


@pytest.mark.django_db
async def test_parse_empty_mutation_counts(clickhouse_client):
    query = f"""
    SELECT mutation_id, is_done
    FROM clusterAllReplicas('posthog', 'system', mutations)
    """

    response = await clickhouse_client.read_query(query)
    mutations_in_progress, total_mutations = parse_mutation_counts(response)
    assert mutations_in_progress == 0
    assert total_mutations == 0


@pytest.mark.django_db
async def test_create_person_distinct_id_overrides_join_table(
    activity_environment, person_overrides_data, clickhouse_client
):
    """Test `person_distinct_id_overrides_join` table creation."""

    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )
    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    for team_id, person_overrides in person_overrides_data.items():
        for person_override in person_overrides:
            query = f"""
            SELECT
                '{person_override.distinct_id}' AS distinct_id,
                joinGet(
                    '{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join',
                    'person_id',
                    toInt64({team_id}),
                    '{person_override.distinct_id}'
                ) AS person_id
            """

            response = await clickhouse_client.read_query(query)
            ids = response.decode("utf-8").strip().split("\t")

            assert ids[0] == person_override.distinct_id
            assert UUID(ids[1]) == person_override.person_id

    await activity_environment.run(drop_table, inputs)


@pytest.mark.django_db
async def test_create_person_distinct_id_overrides_join_with_older_overrides_present(
    activity_environment,
    person_overrides_data,
    older_overrides,
    clickhouse_client,
):
    """Test `person_distinct_id_overrides_join` table contains latest available mappings.

    Since `person_distinct_id_overrides` is using a 'ReplacingMergeTree' engine, the latest version
    should be the only available in the dictionary.
    """
    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    for team_id, person_overrides in person_overrides_data.items():
        for person_override in person_overrides:
            query = f"""
            SELECT
                '{person_override.distinct_id}' AS distinct_id,
                joinGet(
                    '{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join',
                    'person_id',
                    toInt64({team_id}),
                    '{person_override.distinct_id}'
                ) AS person_id
            """
            response = await clickhouse_client.read_query(query)

            ids = response.decode("utf-8").strip().split("\t")

            assert ids[0] == person_override.distinct_id
            assert UUID(ids[1]) == person_override.person_id

    await activity_environment.run(drop_table, inputs)


@pytest.mark.django_db
async def test_create_wait_and_drop_table(activity_environment, person_overrides_data, clickhouse_client):
    """Test if a table is created, waited on, and dropped in a normal workflow."""
    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    # Ensure we are starting from scratch
    await clickhouse_client.execute_query(f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{inputs.name}")
    response = await clickhouse_client.read_query(f"EXISTS TABLE {settings.CLICKHOUSE_DATABASE}.{inputs.name}")
    before = int(response.splitlines()[0])
    assert before == 0

    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    response = await clickhouse_client.read_query(f"EXISTS TABLE {settings.CLICKHOUSE_DATABASE}.{inputs.name}")
    during = int(response.splitlines()[0])
    assert during == 1

    await activity_environment.run(drop_table, inputs)
    inputs.exists = False
    await activity_environment.run(wait_for_table, inputs)

    response = await clickhouse_client.read_query(f"EXISTS TABLE {settings.CLICKHOUSE_DATABASE}.{inputs.name}")
    after = int(response.splitlines()[0])
    assert after == 0


class EventValues(TypedDict):
    """Events to be inserted for testing."""

    uuid: UUID
    event: str
    timestamp: datetime
    person_id: str
    team_id: int


@pytest_asyncio.fixture
async def events_to_override(person_overrides_data, clickhouse_client):
    """Produce some test events for testing.

    These events will be yielded so that we can re-fetch them and assert their
    person_ids have been overriden.
    """
    all_test_events = []
    for team_id, person_ids in person_overrides_data.items():
        for distinct_id, _ in person_ids:
            values = {
                "uuid": uuid4(),
                "event": "test-event",
                "timestamp": EVENT_TIMESTAMP,
                "team_id": team_id,
                "person_id": uuid4(),
                "distinct_id": distinct_id,
            }
            all_test_events.append(values)

    await clickhouse_client.execute_query(
        "INSERT INTO sharded_events FORMAT JSONEachRow",
        *all_test_events,
    )

    yield all_test_events

    await clickhouse_client.execute_query("TRUNCATE TABLE sharded_events")


async def assert_events_have_been_overriden(overriden_events, person_overrides):
    """Assert each event in overriden_events has actually been overriden.

    We use person_overrides to assert the person_id of each event now matches the
    overriden_person_id.
    """
    async with get_client() as clickhouse_client:
        for event in overriden_events:
            response = await clickhouse_client.read_query(
                "SELECT uuid, event, team_id, distinct_id, person_id FROM events WHERE uuid = %(uuid)s",
                query_parameters={"uuid": event["uuid"]},
            )
            row = response.decode("utf-8").splitlines()[0]
            values = list(row.split("\t"))
            new_event = {
                "uuid": UUID(values[0]),
                "event": values[1],
                "team_id": int(values[2]),
                "distinct_id": values[3],
                "person_id": UUID(values[4]),
            }

            assert event["uuid"] == new_event["uuid"]  # Sanity check
            assert event["team_id"] == new_event["team_id"]  # Sanity check
            assert event["event"] == new_event["event"]  # Sanity check
            assert event["person_id"] != new_event["person_id"]

            # If all is well, we should have overriden old_person_id with an override_person_id.
            # Let's find it first:
            new_person_id = [
                person_override.person_id
                for person_override in person_overrides[new_event["team_id"]]
                if person_override.distinct_id == event["distinct_id"]
            ]
            assert new_event["person_id"] == new_person_id[0]


@pytest_asyncio.fixture
async def overrides_join_table(person_overrides_data, activity_environment):
    """Create a person overrides JOIN table testing.

    Some activities that run in unit tests depend on the overrides JOIN table. We create the table in
    this fixture to avoid having to copy the creation activity on every unit test that needs it. This way,
    we can keep the unit tests centered around only the activity they are testing. The tests that run the
    entire Workflow will already include these steps as part of the workflow, so the fixture is not needed.
    """
    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    yield "person_distinct_id_overrides_join"

    await activity_environment.run(drop_table, inputs)


@pytest.mark.django_db
async def test_update_events_with_person_overrides_mutation(
    overrides_join_table,
    activity_environment,
    person_overrides_data,
    events_to_override,
    clickhouse_client,
):
    """Test events are properly squashed by with the update_events_with_person_overrides mutation.

    After running update_events_with_person_overrides, we iterate over the test events created by
    events_to_override and check the person_id associated with each of them. It should
    match the override_person_id associated with the old_person_id they used to be set to.
    """
    mutation_activity_inputs = MutationActivityInputs(
        name="update_events_with_person_overrides",
        query_parameters={},
    )

    mutation_query = await activity_environment.run(submit_mutation, mutation_activity_inputs)

    # We split as we don't care about whitespace matching.
    assert (
        mutation_query.split()
        == f"""
ALTER TABLE
    {settings.CLICKHOUSE_DATABASE}.sharded_events
ON CLUSTER
    {settings.CLICKHOUSE_CLUSTER}
UPDATE
    person_id = joinGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id)
WHERE
    (joinGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id) != defaultValueOfTypeName('UUID'))
SETTINGS
    max_execution_time = 0
    """.split()
    )

    await activity_environment.run(wait_for_mutation, mutation_activity_inputs)

    await assert_events_have_been_overriden(events_to_override, person_overrides_data)


@pytest.mark.django_db
async def test_update_events_with_person_overrides_mutation_with_older_overrides(
    activity_environment,
    person_overrides_data,
    events_to_override,
    older_overrides,
):
    """Test events are properly squashed even in the prescence of older overrides.

    If we get an override from Postgres we can be sure it's the only one for a given
    old_person_id as PG constraints enforce uniqueness on the mapping. However, ClickHouse
    doesn't enforce any kind of uniqueness constraints, so our queries need to be aware there
    could be duplicate overrides present, either in the partition we are currently working
    with as well as older ones.
    """
    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    mutation_activity_inputs = MutationActivityInputs(
        name="update_events_with_person_overrides",
        query_parameters={},
    )
    await activity_environment.run(submit_mutation, mutation_activity_inputs)
    await activity_environment.run(wait_for_mutation, mutation_activity_inputs)

    await assert_events_have_been_overriden(events_to_override, person_overrides_data)


@pytest.mark.django_db
async def test_update_events_with_person_overrides_mutation_with_newer_overrides(
    activity_environment,
    overrides_join_table,
    person_overrides_data,
    events_to_override,
    newer_overrides,
    clickhouse_client,
):
    """Test events are properly squashed even in the prescence of newer overrides.

    If we get an override from Postgres we can get be sure it's the only one for a given
    old_person_id as PG constraints enforce uniqueness on the mapping. However, ClickHouse
    doesn't enforce any kind of uniqueness constraints, so our queries need to be aware there
    could be duplicate overrides present, either in the partition we are currently working
    with as well as newer ones.
    """
    inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    await activity_environment.run(create_table, inputs)
    await activity_environment.run(wait_for_table, inputs)

    mutation_activity_inputs = MutationActivityInputs(
        name="update_events_with_person_overrides",
        query_parameters={},
    )
    await activity_environment.run(submit_mutation, mutation_activity_inputs)
    await activity_environment.run(wait_for_mutation, mutation_activity_inputs)

    await assert_events_have_been_overriden(events_to_override, newer_overrides)


async def create_overrides_join_table_helper(activity_environment) -> TableActivityInputs:
    """Helper function to create overrides join table in test functions."""

    join_table_inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )

    await activity_environment.run(create_table, join_table_inputs)
    await activity_environment.run(wait_for_table, join_table_inputs)

    return join_table_inputs


async def run_squash_mutation_helper(activity_environment) -> None:
    """Helper function to run the Squash mutation in test functions."""
    squash_mutation_activity_inputs = MutationActivityInputs(
        name="update_events_with_person_overrides",
        query_parameters={},
    )
    await activity_environment.run(submit_mutation, squash_mutation_activity_inputs)
    await activity_environment.run(wait_for_mutation, squash_mutation_activity_inputs)


@pytest.mark.django_db
async def test_delete_person_overrides_mutation(
    activity_environment, events_to_override, person_overrides_data, clickhouse_client
):
    """Test we can delete person overrides that have already been squashed.

    For the purposes of this unit test, we take the person overrides as given. A
    comprehensive test will cover the entire worflow end-to-end.

    We insert an extra person to ensure we are not deleting persons we shouldn't
    delete.
    """
    not_overriden_distinct_id = str(uuid4())
    not_overriden_person = {
        "team_id": 1,
        "distinct_id": not_overriden_distinct_id,
        "person_id": uuid4(),
        "version": LATEST_VERSION,
    }

    await clickhouse_client.execute_query(
        "INSERT INTO person_distinct_id_overrides FORMAT JSONEachRow", not_overriden_person
    )

    await create_overrides_join_table_helper(activity_environment)
    await run_squash_mutation_helper(activity_environment)

    delete_table_inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join_to_delete",
        query_parameters={},
    )

    await activity_environment.run(create_table, delete_table_inputs)
    await activity_environment.run(wait_for_table, delete_table_inputs)

    mutation_activity_inputs = MutationActivityInputs(
        name="delete_person_overrides",
        query_parameters={"grace_period": 111111},
    )
    mutation_query = await activity_environment.run(submit_mutation, mutation_activity_inputs)

    assert (
        mutation_query.split()
        == f"""
ALTER TABLE
    {settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides
ON CLUSTER
    {settings.CLICKHOUSE_CLUSTER}
DELETE WHERE
    (joinGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join_to_delete', 'total_not_override_person_id', team_id, distinct_id) = 0)
    AND (joinGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join_to_delete', 'total_override_person_id', team_id, distinct_id) > 0)
    AND ((now() - _timestamp) > 111111)
    AND (joinGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides_join', 'latest_version', team_id, distinct_id) >= version)
SETTINGS
    max_execution_time = 0
    """.split()
    )

    await activity_environment.run(wait_for_mutation, mutation_activity_inputs)

    response = await clickhouse_client.read_query(
        "SELECT team_id, distinct_id, person_id FROM person_distinct_id_overrides"
    )
    rows = response.decode("utf-8").splitlines()

    assert len(rows) == 1

    row = rows[0].split("\t")
    assert int(row[0]) == 1
    assert row[1] == not_overriden_person["distinct_id"]
    assert UUID(row[2]) == not_overriden_person["person_id"]

    await activity_environment.run(drop_table, delete_table_inputs)
    join_table_inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )
    await activity_environment.run(drop_table, join_table_inputs)


@pytest.mark.django_db
async def test_delete_person_overrides_mutation_within_grace_period(
    activity_environment, events_to_override, person_overrides_data, clickhouse_client
):
    """Test we do not delete person overrides if they are within the grace period."""
    now = datetime.now(tz=UTC)
    override_timestamp = int(now.timestamp())
    team_id, person_override = next(iter(person_overrides_data.items()))
    distinct_id, _ = next(iter(person_override))

    not_deleted_person = {
        "team_id": team_id,
        "distinct_id": distinct_id,
        "person_id": str(uuid4()),
        "version": LATEST_VERSION + 1,
        "_timestamp": override_timestamp,
    }

    await clickhouse_client.execute_query(
        "INSERT INTO person_distinct_id_overrides FORMAT JSONEachRow", not_deleted_person
    )

    await create_overrides_join_table_helper(activity_environment)
    await run_squash_mutation_helper(activity_environment)

    delete_table_inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join_to_delete",
        query_parameters={},
    )

    await activity_environment.run(create_table, delete_table_inputs)
    await activity_environment.run(wait_for_table, delete_table_inputs)

    # Assume it will take less than 120 seconds to run the rest of the test.
    # So the row we have added should not be deleted like all the others as its _timestamp
    # was just computed from datetime.now.
    mutation_activity_inputs = MutationActivityInputs(
        name="delete_person_overrides",
        query_parameters={"grace_period": 120},
    )

    await activity_environment.run(submit_mutation, mutation_activity_inputs)
    await activity_environment.run(wait_for_mutation, mutation_activity_inputs)

    response = await clickhouse_client.read_query(
        "SELECT team_id, distinct_id, person_id, _timestamp FROM person_distinct_id_overrides"
    )
    rows = response.decode("utf-8").splitlines()

    assert len(rows) == 1, "Only the override within grace period should be left, but more found that were not deleted"

    row = rows[0].split("\t")
    assert int(row[0]) == not_deleted_person["team_id"]
    assert row[1] == not_deleted_person["distinct_id"]
    assert UUID(row[2]) == UUID(not_deleted_person["person_id"])
    _timestamp = datetime.strptime(row[3], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    # _timestamp is up to second precision
    assert _timestamp == now.replace(microsecond=0)

    await activity_environment.run(drop_table, delete_table_inputs)
    join_table_inputs = TableActivityInputs(
        name="person_distinct_id_overrides_join",
        query_parameters={},
    )
    await activity_environment.run(drop_table, join_table_inputs)


@pytest.mark.django_db
async def test_squash_person_overrides_workflow(
    events_to_override,
    person_overrides_data,
    clickhouse_client,
):
    """Test the squash_person_overrides workflow end-to-end."""
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    workflow_id = str(uuid4())
    inputs = SquashPersonOverridesInputs()

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[SquashPersonOverridesWorkflow],
        activities=[
            create_table,
            drop_table,
            submit_mutation,
            wait_for_mutation,
            wait_for_table,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await client.execute_workflow(
            SquashPersonOverridesWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )

    await assert_events_have_been_overriden(events_to_override, person_overrides_data)

    response = await clickhouse_client.read_query("SELECT team_id, old_person_id FROM person_overrides")
    rows = response.splitlines()
    assert len(rows) == 0


@pytest.mark.django_db
async def test_squash_person_overrides_workflow_with_newer_overrides(
    events_to_override,
    person_overrides_data,
    newer_overrides,
):
    """Test the squash_person_overrides workflow end-to-end with newer overrides."""
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    workflow_id = str(uuid4())
    inputs = SquashPersonOverridesInputs()

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[SquashPersonOverridesWorkflow],
        activities=[
            create_table,
            drop_table,
            submit_mutation,
            wait_for_mutation,
            wait_for_table,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await client.execute_workflow(
            SquashPersonOverridesWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )

    await assert_events_have_been_overriden(events_to_override, newer_overrides)
