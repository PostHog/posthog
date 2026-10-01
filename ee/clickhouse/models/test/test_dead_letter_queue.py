import json
from datetime import datetime
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE, INSERT_DEAD_LETTER_QUEUE_EVENT_SQL
from posthog.kafka_client.topics import KAFKA_DEAD_LETTER_QUEUE

from ee.clickhouse.models.test.utils.util import delay_until_clickhouse_consumes_from_kafka

# The test database has no Kafka tables, so the test brings its own consumer for the dead letter queue topic.
KAFKA_TABLE = f"kafka_{DEAD_LETTER_QUEUE_TABLE}"
KAFKA_TABLE_MV = f"{DEAD_LETTER_QUEUE_TABLE}_mv"
CREATE_KAFKA_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {KAFKA_TABLE}
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
) ENGINE = Kafka(
    {settings.CLICKHOUSE_KAFKA_NAMED_COLLECTION},
    kafka_topic_list = '{KAFKA_DEAD_LETTER_QUEUE}',
    kafka_group_name = 'group1',
    kafka_format = 'JSONEachRow'
)
SETTINGS kafka_skip_broken_messages = 1000
"""
CREATE_KAFKA_TABLE_MV_SQL = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {KAFKA_TABLE_MV} TO writable_{DEAD_LETTER_QUEUE_TABLE}
AS SELECT *, _timestamp, _offset FROM {KAFKA_TABLE}
"""

TEST_EVENT_RAW_PAYLOAD = json.dumps({"event": "some event", "properties": {"distinct_id": 2, "token": "invalid token"}})


def get_dlq_event():
    CREATED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    ERROR_TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    return {
        "id": str(uuid4()),
        "event_uuid": str(uuid4()),
        "event": "some event",
        "properties": "{ a: 1 }",
        "distinct_id": "some distinct id",
        "team_id": 1,
        "elements_chain": "",
        "created_at": CREATED_AT,
        "ip": "127.0.0.1",
        "site_url": "https://myawesomewebsite.com",
        "now": NOW,
        "raw_payload": TEST_EVENT_RAW_PAYLOAD,
        "error_timestamp": ERROR_TIMESTAMP,
        "error_location": "plugin-server",
        "error": "createPerson failed",
    }


def convert_query_result_to_dlq_event_dicts(query_result):
    events_returned = []

    for read_dlq_event in query_result:
        events_returned.append(
            {
                "id": str(read_dlq_event[0]),
                "event_uuid": str(read_dlq_event[1]),
                "event": str(read_dlq_event[2]),
                "properties": str(read_dlq_event[3]),
                "distinct_id": str(read_dlq_event[4]),
                "team_id": int(read_dlq_event[5]),
                "elements_chain": str(read_dlq_event[6]),
                "created_at": read_dlq_event[7].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "ip": str(read_dlq_event[8]),
                "site_url": str(read_dlq_event[9]),
                "now": read_dlq_event[10].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "raw_payload": str(read_dlq_event[11]),
                "error_timestamp": read_dlq_event[12].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "error_location": str(read_dlq_event[13]),
                "error": str(read_dlq_event[14]),
            }
        )
    return events_returned


class TestDeadLetterQueue(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        sync_execute(CREATE_KAFKA_TABLE_SQL)
        sync_execute(CREATE_KAFKA_TABLE_MV_SQL)
        super().setUp()

    def tearDown(self):
        sync_execute(f"DROP TABLE IF EXISTS {KAFKA_TABLE_MV}")
        sync_execute(f"DROP TABLE IF EXISTS {KAFKA_TABLE}")
        super().tearDown()

    def test_direct_table_insert(self):
        inserted_dlq_event = get_dlq_event()
        sync_execute(INSERT_DEAD_LETTER_QUEUE_EVENT_SQL, inserted_dlq_event)
        query_result = sync_execute(f"SELECT * FROM {DEAD_LETTER_QUEUE_TABLE}")
        events_returned = convert_query_result_to_dlq_event_dicts(query_result)
        # TRICKY: because it's hard to truncate the dlq table, we just check if the event is in the table along with events from other tests
        # Because each generated event is unique, this works
        self.assertIn(inserted_dlq_event, events_returned)

    def test_kafka_insert(self):
        row_count_before_insert = sync_execute(f"SELECT count(1) FROM {DEAD_LETTER_QUEUE_TABLE}")[0][0]
        inserted_dlq_event = get_dlq_event()

        new_error = "cannot reach db to fetch team"
        inserted_dlq_event["error"] = new_error

        kafka_producer = KafkaProducer(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)

        kafka_producer.send(
            topic=KAFKA_DEAD_LETTER_QUEUE,
            value=json.dumps(inserted_dlq_event).encode("utf-8"),
        )

        delay_until_clickhouse_consumes_from_kafka(DEAD_LETTER_QUEUE_TABLE, row_count_before_insert + 1)

        query_result = sync_execute(f"SELECT * FROM {DEAD_LETTER_QUEUE_TABLE}")
        events_returned = convert_query_result_to_dlq_event_dicts(query_result)
        # TRICKY: because it's hard to truncate the dlq table, we just check if the event is in the table along with events from other tests
        # Because each generated event is unique, this works
        self.assertIn(inserted_dlq_event, events_returned)
