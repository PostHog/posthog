# explicit fixture import is needed as autodiscovery doesn't work due to package layout
from posthog.conftest import django_db_setup, unittest_snapshot

__all__ = ["django_db_setup", "unittest_snapshot"]

from collections.abc import Iterator

import pytest

from posthog.test.base import reset_clickhouse_database
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    reset_clickhouse_database()
    try:
        yield get_cluster()
    finally:
        reset_clickhouse_database()
