import json
from datetime import datetime
from uuid import UUID, uuid4

from kafka import KafkaProducer

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.test.utils.util import delay_until_clickhouse_consumes_from_kafka
from ee.clickhouse.sql.person import INSERT_PERSON_SQL, PERSONS_TABLE
from ee.clickhouse.util import ClickhouseTestMixin
from ee.kafka_client.topics import KAFKA_PERSON
from posthog.settings import KAFKA_HOSTS
from posthog.test.base import BaseTest

TEST_DATA = {
    "id": str(uuid4()),
    "team_id": 99,
    "properties": "{ a: 1 }",
    "is_identified": 1,
    "is_deleted": 0,
    "version": 0,
    "_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}


def reset_tables():
    sync_execute("TRUNCATE TABLE person")


class TestPersonsTable(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        reset_tables()

    def test_replacing_merge_tree(self):

        person1 = TEST_DATA.copy()
        person1["version"] = 1

        person2 = TEST_DATA.copy()
        person2["version"] = 2

        person3 = TEST_DATA.copy()
        person3["version"] = 3
        person3["is_deleted"] = 1

        person4 = TEST_DATA.copy()
        person4["version"] = 4
        person4["is_deleted"] = 1

        sync_execute(INSERT_PERSON_SQL, person1)
        sync_execute(INSERT_PERSON_SQL, person2)
        sync_execute(INSERT_PERSON_SQL, person3)
        sync_execute(INSERT_PERSON_SQL, person4)

        persons = sync_execute("SELECT version, is_deleted FROM person FINAL")

        self.assertEqual(len(persons), 1)

        self.assertEqual(persons[0][0], 4)  # version
        self.assertEqual(persons[0][1], 1)  # is_deleted

    def test_kafka_insert(self):

        kafka_person1 = TEST_DATA.copy()
        kafka_person1["version"] = 2
        kafka_person1["is_deleted"] = 1

        kafka_person2 = TEST_DATA.copy()
        kafka_person2["version"] = 100

        kafka_producer = KafkaProducer(bootstrap_servers=KAFKA_HOSTS)

        kafka_producer.send(topic=KAFKA_PERSON, value=json.dumps(kafka_person1).encode("utf-8"))
        kafka_producer.send(topic=KAFKA_PERSON, value=json.dumps(kafka_person2).encode("utf-8"))

        delay_until_clickhouse_consumes_from_kafka(PERSONS_TABLE, 1, timeout_seconds=10)

        persons = sync_execute("SELECT version, is_deleted FROM person FINAL")

        # the person with is_deleted = 1 gets assigned a version = max(uint64)
        # this ensures all other rows will be collapsed and we'll keep the record
        # of the person being deleted
        self.assertEqual(len(persons), 1)

        self.assertEqual(persons[0][0], 2 ** 64 - 1)  # version
        self.assertEqual(persons[0][1], 1)  # is_deleted
