import json
from datetime import datetime, timedelta
from time import sleep
from typing import List, cast
from uuid import uuid4

import pytest
import pytz
from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.models.person_overrides.sql import (
    DROP_KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    DROP_PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
)
from posthog.settings.data_stores import KAFKA_HOSTS


@pytest.mark.django_db
def test_can_insert_person_overrides():
    # By default the test suite runs with ClickHouse no Kafka or Materialixzed
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
        oldest_event = datetime.fromisoformat(oldest_event_string).replace(tzinfo=pytz.UTC)
        merged_at_string = "2020-01-02 00:00:00"
        merged_at = datetime.fromisoformat(merged_at_string).replace(tzinfo=pytz.UTC)
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

        results = cast(List, results)
        assert results != []
        [result] = results
        created_at, *the_rest = result
        assert the_rest == [1, old_person_id, override_person_id, oldest_event, merged_at, 2]
        assert created_at > datetime.now(tz=pytz.UTC) - timedelta(seconds=10)
    finally:
        producer.close()

        sync_execute(DROP_KAFKA_PERSON_OVERRIDES_TABLE_SQL)
        sync_execute(DROP_PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL)
