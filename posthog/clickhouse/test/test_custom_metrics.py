from collections.abc import Iterator

import pytest
from posthog.test.base import reset_clickhouse_database

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.clickhouse.custom_metrics import MetricsClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    reset_clickhouse_database()
    try:
        yield get_cluster()
    finally:
        reset_clickhouse_database()


def test_increment_without_counter_table_does_nothing(cluster: ClickhouseCluster) -> None:
    # Only PostHog Cloud has custom_metrics_counter_events, so test databases do not.
    assert MetricsClient(cluster).increment("example", labels={"a": "1"}).result() is None
