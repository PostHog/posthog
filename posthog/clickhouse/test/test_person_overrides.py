import json
from time import sleep
from typing import List, cast
from uuid import uuid4

import pytest
from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.settings.data_stores import KAFKA_HOSTS


@pytest.mark.django_db
def test_can_insert_person_overrides():
    producer = KafkaProducer(bootstrap_servers=KAFKA_HOSTS)
    try:
        future = producer.send(
            topic=KAFKA_PERSON_OVERRIDE,
            key=str(uuid4()).encode("utf-8"),
            value=json.dumps(
                {
                    "team_id": 1,
                    "old_person_id": str(uuid4()),
                    "override_person_id": str(uuid4()),
                    "oldest_event": "2020-01-01 00:00:00",
                    "merged_at": "2020-01-01 00:00:00",
                    "created_at": "2020-01-01 00:00:00",
                    "version": 1,
                }
            ).encode("utf-8"),
        )

        future.get(timeout=5)  # Wait for an ack from Kafka

        # Wait up to 10 seconds for ClickHouse to consume the message
        results = []
        for _ in range(10):
            results = sync_execute("SELECT * FROM person_overrides")
            if results:
                break
            sleep(1)

        results = cast(List, results)
        assert len(results) == 1
    finally:
        producer.close()
