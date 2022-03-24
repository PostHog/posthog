import json
from datetime import datetime
from uuid import UUID, uuid4

from kafka import KafkaProducer

from ee.clickhouse.models.test.utils.util import delay_until_clickhouse_consumes_from_kafka
from ee.clickhouse.sql.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE, INSERT_DEAD_LETTER_QUEUE_EVENT_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from ee.kafka_client.topics import KAFKA_DEAD_LETTER_QUEUE
from posthog.client import sync_execute
from posthog.settings import KAFKA_HOSTS
from posthog.test.base import BaseTest

TEST_EVENT_RAW_PAYLOAD = json.dumps(
    {"event": "some event", "properties": {"distinct_id": 2, "token": "invalid token",},}
)

CREATED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
ERROR_TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


TEST_DATA = {
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


def reset_tables():
    sync_execute("TRUNCATE TABLE events_dead_letter_queue")

    # We can't truncate a table using Kafka engine but reading from it will delete all the rows
    # Note: ClickHouse version >= 21.12 do not allow direct select for Kafka/RabbitMQ/FileLog engine tables.
    #       We can pass `stream_like_engine_allow_direct_select` to override this behavior.
    sync_execute("SELECT * FROM kafka_events_dead_letter_queue", settings={"stream_like_engine_allow_direct_select": 1})


class TestDeadLetterQueue(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        reset_tables()

    def test_direct_table_insert(self):

        sync_execute(
            INSERT_DEAD_LETTER_QUEUE_EVENT_SQL, TEST_DATA,
        )

        dead_letter_queue_events = sync_execute("SELECT * FROM events_dead_letter_queue LIMIT 1")

        dlq_event = dead_letter_queue_events[0]

        self.assertEqual(type(dlq_event[0]), UUID)  # id
        self.assertEqual(type(dlq_event[1]), UUID)  # event_uuid
        self.assertEqual(dlq_event[2], "some event")  # event
        self.assertEqual(dlq_event[3], "{ a: 1 }")  # properties
        self.assertEqual(dlq_event[4], "some distinct id")  # distinct_id
        self.assertEqual(dlq_event[5], 1)  # team_id
        self.assertEqual(dlq_event[6], "")  # elements_chain
        self.assertEqual(dlq_event[7].strftime("%Y-%m-%d %H:%M:%S.%f"), CREATED_AT)  # created_at
        self.assertEqual(dlq_event[8], "127.0.0.1")  # ip
        self.assertEqual(dlq_event[9], "https://myawesomewebsite.com")  # site_url
        self.assertEqual(dlq_event[10].strftime("%Y-%m-%d %H:%M:%S.%f"), NOW)  # now
        self.assertEqual(dlq_event[11], TEST_EVENT_RAW_PAYLOAD)  # raw_payload
        self.assertEqual(dlq_event[12].strftime("%Y-%m-%d %H:%M:%S.%f"), ERROR_TIMESTAMP)  # created_at
        self.assertEqual(dlq_event[13], "plugin-server")  # error_location
        self.assertEqual(dlq_event[14], "createPerson failed")  # error

    def test_kafka_insert(self):

        kafka_data = TEST_DATA

        new_id = str(uuid4())
        kafka_data["id"] = new_id

        new_event_uuid = str(uuid4())
        kafka_data["event_uuid"] = new_event_uuid

        new_error = "cannot reach db to fetch team"
        kafka_data["error"] = new_error

        kafka_producer = KafkaProducer(bootstrap_servers=KAFKA_HOSTS)

        kafka_producer.send(topic=KAFKA_DEAD_LETTER_QUEUE, value=json.dumps(kafka_data).encode("utf-8"))

        delay_until_clickhouse_consumes_from_kafka(DEAD_LETTER_QUEUE_TABLE, 1)

        dead_letter_queue_events = sync_execute(f"SELECT * FROM {DEAD_LETTER_QUEUE_TABLE} LIMIT 1")

        dlq_event = dead_letter_queue_events[0]

        self.assertEqual(str(dlq_event[0]), new_id)  # id
        self.assertEqual(str(dlq_event[1]), new_event_uuid)  # event_uuid
        self.assertEqual(dlq_event[2], "some event")  # event
        self.assertEqual(dlq_event[3], "{ a: 1 }")  # properties
        self.assertEqual(dlq_event[4], "some distinct id")  # distinct_id
        self.assertEqual(dlq_event[5], 1)  # team_id
        self.assertEqual(dlq_event[6], "")  # elements_chain
        self.assertEqual(dlq_event[7].strftime("%Y-%m-%d %H:%M:%S.%f"), CREATED_AT)  # created_at
        self.assertEqual(dlq_event[8], "127.0.0.1")  # ip
        self.assertEqual(dlq_event[9], "https://myawesomewebsite.com")  # site_url
        self.assertEqual(dlq_event[10].strftime("%Y-%m-%d %H:%M:%S.%f"), NOW)  # now
        self.assertEqual(dlq_event[11], TEST_EVENT_RAW_PAYLOAD)  # raw_payload
        self.assertEqual(dlq_event[12].strftime("%Y-%m-%d %H:%M:%S.%f"), ERROR_TIMESTAMP)  # created_at
        self.assertEqual(dlq_event[13], "plugin-server")  # error_location
        self.assertEqual(dlq_event[14], new_error)  # error
