import re
from pathlib import Path

from posthog.clickhouse.schema import CREATE_KAFKA_TABLE_QUERIES, build_query
from posthog.settings.data_stores import SUFFIX
from posthog.settings.kafka import KAFKA_PREFIX


def _kafka_topics_in_schema() -> set[str]:
    # Topic names are built as KAFKA_PREFIX + name + SUFFIX, and the test settings set a
    # suffix the dev stack does not use. Compare the bare names the bootstrap file holds.
    topics: set[str] = set()
    for query in CREATE_KAFKA_TABLE_QUERIES:
        sql = build_query(query)
        topics.update(re.findall(r"kafka_topic_list\s*=\s*'([^']+)'", sql))
        topics.update(re.findall(r"Kafka\('[^']*',\s*'([^']+)'", sql))
    return {t.removeprefix(KAFKA_PREFIX).removesuffix(SUFFIX) for t in topics}


def test_dev_stack_pre_creates_every_kafka_table_topic():
    bootstrap = Path(__file__).parents[3] / "docker" / "kafka" / "topics.txt"
    listed = {
        stripped
        for line in bootstrap.read_text().splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    }

    missing = sorted(_kafka_topics_in_schema() - listed)

    assert not missing, (
        f"{bootstrap.name} does not list {missing}. A ClickHouse Kafka table whose topic is "
        "absent never gets a partition assignment, so it holds a thread and repeats the "
        "request for as long as a local stack runs. Add each topic to that file."
    )
