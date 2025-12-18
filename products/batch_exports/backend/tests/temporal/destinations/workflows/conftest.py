import random
import string
import typing

import pytest

import aiokafka
import aiokafka.admin
import pytest_asyncio


@pytest.fixture
def security_protocol():
    security_protocol: typing.Literal["PLAINTEXT", "SSL"] = "PLAINTEXT"
    return security_protocol


@pytest.fixture
def hosts() -> list[str]:
    return ["kafka:9092"]


@pytest_asyncio.fixture
async def topic(hosts):
    admin_client = aiokafka.admin.AIOKafkaAdminClient(bootstrap_servers=hosts, security_protocol="PLAINTEXT")
    random_string = "".join(random.choices(string.ascii_letters, k=10))
    test_topic = f"test_batch_exports_{random_string}"

    await admin_client.start()
    await admin_client.create_topics([aiokafka.admin.NewTopic(name=test_topic, num_partitions=1, replication_factor=1)])

    yield test_topic

    await admin_client.delete_topics([test_topic])
    await admin_client.close()


@pytest.fixture
def events_table() -> str:
    return "sharded_events"
