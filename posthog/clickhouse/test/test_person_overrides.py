import json
from datetime import datetime, timedelta, UTC
from time import sleep
from typing import TypedDict
from uuid import UUID, uuid4

import pytest
from zoneinfo import ZoneInfo
from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.models.person_overrides.sql import (
    DROP_KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    DROP_PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    PERSON_OVERRIDES_CREATE_DICTIONARY_SQL,
    PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    PERSON_OVERRIDES_CREATE_TABLE_SQL,
)
from posthog.settings.data_stores import KAFKA_HOSTS


@pytest.mark.django_db
def test_can_insert_person_overrides():
    # By default the test suite runs with ClickHouse no Kafka or Materialized
    # Views. Updating to include these seems to be a [larger task to
    # fix](https://github.com/PostHog/posthog/pull/13878), so here we create
    # just the missing tables we need to verify functionality.
    sync_execute(KAFKA_PERSON_OVERRIDES_TABLE_SQL)
    sync_execute(PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL)

    producer = KafkaProducer(bootstrap_servers=KAFKA_HOSTS)
    try:
        old_person_id = uuid4()
        override_person_id = uuid4()
        oldest_event_string = "2020-01-01 00:00:00"
        oldest_event = datetime.fromisoformat(oldest_event_string).replace(tzinfo=ZoneInfo("UTC"))
        merged_at_string = "2020-01-02 00:00:00"
        merged_at = datetime.fromisoformat(merged_at_string).replace(tzinfo=ZoneInfo("UTC"))
        message = {
            "team_id": 1,
            "old_person_id": str(old_person_id),
            "override_person_id": str(override_person_id),
            "oldest_event": oldest_event_string,
            "merged_at": merged_at_string,
            "version": 2,
        }
        future = producer.send(
            topic=KAFKA_PERSON_OVERRIDE,
            key=str(uuid4()).encode("utf-8"),
            value=json.dumps(message).encode("utf-8"),
        )

        future.get(timeout=5)  # Wait for an ack from Kafka

        # Wait up to 5 tries for ClickHouse to consume the message
        results = []
        for _ in range(5):
            results = sync_execute(
                """
                SELECT
                    created_at,
                    team_id,
                    old_person_id,
                    override_person_id,
                    oldest_event,
                    merged_at,
                    version
                FROM
                    person_overrides
                WHERE old_person_id = %(old_person_id)s
                """,
                {"old_person_id": str(old_person_id)},
            )
            if results:
                break
            sleep(1)

        assert isinstance(results, list)
        assert results != []
        [result] = results
        created_at, *the_rest = result
        assert the_rest == [
            1,
            old_person_id,
            override_person_id,
            oldest_event,
            merged_at,
            2,
        ]
        assert created_at > datetime.now(tz=ZoneInfo("UTC")) - timedelta(seconds=10)
    finally:
        producer.close()

        sync_execute(DROP_KAFKA_PERSON_OVERRIDES_TABLE_SQL)
        sync_execute(DROP_PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL)


class PersonOverrideValues(TypedDict):
    """A dict of values that may be inserted into person_overrides."""

    team_id: int
    old_person_id: UUID
    override_person_id: UUID
    merged_at: datetime
    oldest_event: datetime
    created_at: datetime
    version: int


@pytest.mark.django_db
def test_person_overrides_dict():
    """Test behavior of person_overrides_dict with multiple versions of same key.

    The dictionary should always favor the latest version after every reload.
    """
    sync_execute(PERSON_OVERRIDES_CREATE_TABLE_SQL)
    sync_execute(PERSON_OVERRIDES_CREATE_DICTIONARY_SQL)

    values: PersonOverrideValues = {
        "team_id": 1,
        "old_person_id": uuid4(),
        "override_person_id": uuid4(),
        "merged_at": datetime.fromisoformat("2020-01-02T00:00:00+00:00"),
        "oldest_event": datetime.fromisoformat("2020-01-01T00:00:00+00:00"),
        "created_at": datetime.now(UTC),
        "version": 1,
    }

    sync_execute("INSERT INTO person_overrides (*) VALUES", [values])
    sync_execute("SYSTEM RELOAD DICTIONARY person_overrides_dict")
    results = sync_execute(
        "SELECT dictGet(person_overrides_dict, 'override_person_id', (%(team_id)s, %(old_person_id)s))",
        values,
    )

    assert len(results) == 1
    assert results[0][0] == values["override_person_id"]

    values["version"] = 2
    values["override_person_id"] = uuid4()

    sync_execute("INSERT INTO person_overrides (*) VALUES", [values])
    sync_execute("SYSTEM RELOAD DICTIONARY person_overrides_dict")
    new_results = sync_execute(
        "SELECT dictGet(person_overrides_dict, 'override_person_id', (%(team_id)s, %(old_person_id)s))",
        values,
    )

    assert len(new_results) == 1
    assert new_results[0][0] == values["override_person_id"]
    assert new_results[0][0] != results[0][0]
