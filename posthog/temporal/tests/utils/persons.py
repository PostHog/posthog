"""Test utilities that deal with test person generation."""

import json
import uuid
import random
import typing
import datetime as dt

from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.datetimes import date_range


class PersonValues(typing.TypedDict):
    """Person values to be inserted for testing."""

    id: str
    created_at: str
    team_id: int
    properties: dict | None
    is_identified: bool
    is_deleted: bool
    version: int
    _timestamp: str


def generate_test_persons(
    count: int,
    team_id: int,
    timestamp_start: dt.datetime,
    timestamp_end: dt.datetime,
    person_id: uuid.UUID | None = None,
    version: int = 1,
    properties: dict | None = None,
    is_identified: bool = True,
    is_deleted: bool = False,
    start: int = 0,
) -> list[PersonValues]:
    """Generate a list of persons for testing."""
    timestamps = random.sample(
        list(date_range(timestamp_start + dt.timedelta(seconds=1) * start, timestamp_end, dt.timedelta(seconds=1))),
        k=count,
    )

    persons: list[PersonValues] = []
    for _ in range(start, count + start):
        timestamp = timestamps.pop()
        person: PersonValues = {
            "id": str(person_id) if person_id else str(uuid.uuid4()),
            "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "team_id": team_id,
            "properties": properties,
            "is_identified": is_identified,
            "is_deleted": is_deleted,
            "version": version,
            "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        }
        persons.append(person)

    return persons


async def insert_person_values_in_clickhouse(client: ClickHouseClient, persons: list[PersonValues]):
    """Execute an insert query to insert provided PersonValues into person."""
    await client.execute_query(
        f"""
        INSERT INTO `person` (
            id,
            team_id,
            created_at,
            properties,
            is_identified,
            is_deleted,
            version,
            _timestamp
        )
        VALUES
        """,
        *[
            (
                person["id"],
                person["team_id"],
                person["created_at"],
                json.dumps(person["properties"]) if isinstance(person["properties"], dict) else person["properties"],
                person["is_identified"],
                person["is_deleted"],
                person["version"],
                person["_timestamp"],
            )
            for person in persons
        ],
    )


async def generate_test_persons_in_clickhouse(
    client: ClickHouseClient,
    team_id: int,
    start_time: dt.datetime,
    end_time: dt.datetime,
    count: int = 100,
    count_other_team: int = 0,
    person_id: uuid.UUID | None = None,
    version: int = 1,
    properties: dict | None = None,
    is_identified: bool = True,
    is_deleted: bool = False,
    batch_size: int = 10000,
) -> tuple[list[PersonValues], list[PersonValues]]:
    persons: list[PersonValues] = []
    while len(persons) < count:
        persons_to_insert = generate_test_persons(
            count=min(count - len(persons), batch_size),
            team_id=team_id,
            timestamp_start=start_time,
            timestamp_end=end_time,
            person_id=person_id,
            properties=properties,
            is_identified=is_identified,
            is_deleted=is_deleted,
            version=version,
            start=len(persons),
        )

        await insert_person_values_in_clickhouse(client=client, persons=persons_to_insert)

        persons.extend(persons_to_insert)

    persons_from_other_team = generate_test_persons(
        count=count_other_team,
        team_id=team_id + random.randint(1, 1000),
        timestamp_start=start_time,
        timestamp_end=end_time,
        person_id=person_id,
        properties=properties,
        is_identified=is_identified,
        is_deleted=is_deleted,
        version=version,
        start=len(persons),
    )

    await insert_person_values_in_clickhouse(client=client, persons=persons_from_other_team)
    return (persons, persons_from_other_team)


class PersonDistinctId2Values(typing.TypedDict):
    """Values to be inserted in person_distinct_id2 for testing."""

    team_id: int
    distinct_id: str
    person_id: str
    is_deleted: bool
    version: int
    _timestamp: str


def generate_test_person_distinct_id2(
    count: int,
    team_id: int,
    timestamp: dt.datetime,
    distinct_id: str,
    person_id: uuid.UUID | None = None,
    version: int = 1,
    is_deleted: bool = False,
) -> PersonDistinctId2Values:
    """Generate a row of person_distinct_id2 values for testing."""
    person: PersonDistinctId2Values = {
        "team_id": team_id,
        "distinct_id": distinct_id,
        "person_id": str(person_id) if person_id else str(uuid.uuid4()),
        "is_deleted": is_deleted,
        "version": version,
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }

    return person


async def insert_person_distinct_id2_values_in_clickhouse(
    client: ClickHouseClient, persons: list[PersonDistinctId2Values]
):
    """Execute an insert query to insert provided PersonDistinctId2Values into person."""
    await client.execute_query(
        f"""
        INSERT INTO `person_distinct_id2` (
             team_id,
             distinct_id,
             person_id,
             is_deleted,
             version,
            _timestamp
        )
        VALUES
        """,
        *[
            (
                person["team_id"],
                person["distinct_id"],
                person["person_id"],
                person["is_deleted"],
                person["version"],
                person["_timestamp"],
            )
            for person in persons
        ],
    )


async def generate_test_person_distinct_id2_in_clickhouse(
    client: ClickHouseClient,
    team_id: int,
    distinct_id: str,
    timestamp: dt.datetime,
    person_id: uuid.UUID | None = None,
    version: int = 1,
    is_deleted: bool = False,
) -> tuple[PersonDistinctId2Values, PersonDistinctId2Values]:
    person = generate_test_person_distinct_id2(
        count=1,
        team_id=team_id,
        timestamp=timestamp,
        distinct_id=distinct_id,
        person_id=person_id,
        is_deleted=is_deleted,
        version=version,
    )

    await insert_person_distinct_id2_values_in_clickhouse(client=client, persons=[person])

    person_from_other_team = generate_test_person_distinct_id2(
        count=1,
        team_id=team_id + random.randint(1, 1000),
        timestamp=timestamp,
        distinct_id=distinct_id,
        person_id=person_id,
        is_deleted=is_deleted,
        version=version,
    )

    await insert_person_distinct_id2_values_in_clickhouse(client=client, persons=[person_from_other_team])
    return (person, person_from_other_team)
