from collections.abc import Iterator

import pytest
from posthog.test.base import reset_clickhouse_database

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster, Query, get_cluster
from posthog.clickhouse.custom_metrics import MetricsClient

pytestmark = pytest.mark.django_db


# Only cloud clusters have the counter table and its view, so the test declares its own copy.
COUNTER_EVENTS_TABLE_SQL = """
CREATE TABLE custom_metrics_counter_events (
    name String,
    timestamp DateTime64(3, 'UTC') DEFAULT now(),
    labels Map(String, String),
    increment Float64
) ENGINE = MergeTree ORDER BY (name, timestamp)
"""
COUNTERS_VIEW_SQL = """
CREATE VIEW custom_metrics_counters AS
SELECT name, mapSort(labels) AS labels, sum(increment) AS value, '' AS help, 'counter' AS type
FROM custom_metrics_counter_events
GROUP BY name, type, labels
ORDER BY name, type, labels
"""


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    reset_clickhouse_database()
    sync_execute(COUNTER_EVENTS_TABLE_SQL)
    sync_execute(COUNTERS_VIEW_SQL)
    try:
        yield get_cluster()
    finally:
        reset_clickhouse_database()


def test_custom_metrics_counters(cluster: ClickhouseCluster) -> None:
    metrics = MetricsClient(cluster)

    query = Query(
        "SELECT name, type, labels, value FROM custom_metrics_counters WHERE name = %(name)s",
        {"name": "example"},
    )

    metrics.increment("example").result()
    assert cluster.any_host(query).result() == [
        ("example", "counter", {}, 1.0),
    ]

    metrics.increment("example", value=2).result()
    assert cluster.any_host(query).result() == [
        ("example", "counter", {}, 3.0),
    ]

    metrics.increment("example", labels={"a": "1"}).result()
    assert cluster.any_host(query).result() == [
        ("example", "counter", {}, 3.0),
        ("example", "counter", {"a": "1"}, 1.0),
    ]
