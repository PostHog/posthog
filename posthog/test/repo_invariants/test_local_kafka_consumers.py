"""Guards for the ClickHouse Kafka tables of a local stack.

A local Kafka table must declare exactly one consumer. The local stacks create
every topic with one partition, so a consumer group can place only one consumer.
Extra consumers never get an assignment. Each one holds a thread and repeats the
request for as long as the stack runs, which burns CPU and floods the server log.
A Kafka table whose topic does not exist behaves the same way, so the stack must
create the topic of every Kafka table before ClickHouse starts.

The schema under posthog/clickhouse/schema/catalog is what the local stacks apply.
A cluster that needs more consumers sets the count in its own root, as an override.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
# hogli clickhouse:logs:init runs this SQL straight at a local server, so it is not part of the schema modules.
EXTRA_LOCAL_SQL = "bin/clickhouse-logs.sql"

_KAFKA_CONSUMERS = re.compile(r'kafka_num_consumers\s*=\s*"?(\d+)')
_KAFKA_TOPIC = re.compile(r'kafka_topic_list\s*=\s*\'([^\']+)\'|\btopic\s*=\s*"([^"\n]+)"')


def _schema_kafka_tables() -> list[Path]:
    return sorted((REPO_ROOT / "posthog" / "clickhouse" / "schema" / "catalog").rglob("*.tf"))


def test_local_kafka_tables_declare_one_consumer() -> None:
    counts = [
        (path.relative_to(REPO_ROOT), int(match.group(1)))
        for path in [*_schema_kafka_tables(), REPO_ROOT / EXTRA_LOCAL_SQL]
        for match in _KAFKA_CONSUMERS.finditer(path.read_text())
    ]
    # A pattern that matches nothing would make the guard vacuous.
    assert counts, "found no kafka_num_consumers setting to check"

    offenders = [f"{path} = {count}" for path, count in counts if count != 1]
    assert not offenders, (
        "These Kafka tables declare more than one consumer on a local stack: "
        + ", ".join(offenders)
        + ". Local topics have one partition, so the extra consumers never get an assignment and "
        "spin instead. Declare one consumer here, and set the higher count as an override in the "
        "root of the cluster that needs it."
    )


def test_dev_stack_pre_creates_every_kafka_table_topic() -> None:
    bootstrap = REPO_ROOT / "docker" / "kafka" / "topics.txt"
    listed = {
        stripped
        for line in bootstrap.read_text().splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    }
    topics = {
        setting or declaration
        for path in _schema_kafka_tables()
        for setting, declaration in _KAFKA_TOPIC.findall(path.read_text())
    }
    assert topics, "found no kafka_topic_list setting to check"

    missing = sorted(topics - listed)
    assert not missing, (
        f"{bootstrap.name} does not list {missing}. A ClickHouse Kafka table whose topic is "
        "absent never gets a partition assignment, so it holds a thread and repeats the "
        "request for as long as a local stack runs. Add each topic to that file."
    )
