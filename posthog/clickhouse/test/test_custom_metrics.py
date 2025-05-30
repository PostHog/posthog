from collections.abc import Iterator

import pytest
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.test.base import reset_clickhouse_database


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    reset_clickhouse_database()
    try:
        yield get_cluster()
    finally:
        reset_clickhouse_database()


def test_custom_metrics_counters(cluster: ClickhouseCluster) -> None:
    metrics = MetricsClient(cluster)
    metrics.increment("example").result()
