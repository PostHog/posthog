import json
from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.dead_letter_queue import INSERT_DEAD_LETTER_QUEUE_EVENT_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import BaseTest

TEST_EVENT_RAW_PAYLOAD = json.dumps(
    {
        "event": "some event",
        "properties": {
            "distinct_id": 2,
            "token": "invalid token",
        },
    }
)

# we do assertions here but mostly this just tests that the table is created successfully and works
# "e2e" tests are more useful
class TestDeadLetterQueue(ClickhouseTestMixin, BaseTest):
    def test_insert_and_retrieve_failed_event(self):
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        error_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        sync_execute(
            INSERT_DEAD_LETTER_QUEUE_EVENT_SQL,
            {
                "id": str(uuid4()),
                "event_uuid": str(uuid4()),
                "event": "some event",
                "properties": "{ a: 1 }",
                "distinct_id": "some distinct id",
                "team_id": 1,
                "elements_chain": "",
                "created_at": created_at,
                "ip": "127.0.0.1",
                "site_url": "https://myawesomewebsite.com",
                "now": now,
                "raw_payload": TEST_EVENT_RAW_PAYLOAD,
                "error_timestamp": error_timestamp,
                "error_location": "plugin-server",
                "error": "createPerson failed",
            },
        )

        dead_letter_queue_events = sync_execute("SELECT * FROM events_dead_letter_queue")

        dlq_event = dead_letter_queue_events[0]

        self.assertEqual(type(dlq_event[0]), UUID)  # id
        self.assertEqual(type(dlq_event[1]), UUID)  # event_uuid
        self.assertEqual(dlq_event[2], "some event")  # event
        self.assertEqual(dlq_event[3], "{ a: 1 }")  # properties
        self.assertEqual(dlq_event[4], "some distinct id")  # distinct_id
        self.assertEqual(dlq_event[5], 1)  # team_id
        self.assertEqual(dlq_event[6], "")  # elements_chain
        self.assertEqual(dlq_event[7].strftime("%Y-%m-%d %H:%M:%S.%f"), created_at)  # created_at
        self.assertEqual(dlq_event[8], "127.0.0.1")  # ip
        self.assertEqual(dlq_event[9], "https://myawesomewebsite.com")  # site_url
        self.assertEqual(dlq_event[10].strftime("%Y-%m-%d %H:%M:%S.%f"), now)  # now
        self.assertEqual(dlq_event[11], TEST_EVENT_RAW_PAYLOAD)  # raw_payload
        self.assertEqual(dlq_event[12].strftime("%Y-%m-%d %H:%M:%S.%f"), error_timestamp)  # created_at
        self.assertEqual(dlq_event[13], "plugin-server")  # error_location
        self.assertEqual(dlq_event[14], "createPerson failed")  # error
