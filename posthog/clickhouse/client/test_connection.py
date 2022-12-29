import pytest

from posthog.clickhouse.client.connection import Workload, get_pool, make_ch_pool


def test_connection_pool_creation_without_offline_cluster(settings):
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = None

    online_pool = get_pool(Workload.ONLINE)
    assert get_pool(Workload.ONLINE) is online_pool
    assert get_pool(Workload.OFFLINE) is online_pool


def test_connection_pool_creation_with_offline_cluster(settings):
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = "ch-offline.example.com"

    online_pool = get_pool(Workload.ONLINE)
    offline_pool = get_pool(Workload.OFFLINE)
    assert get_pool(Workload.ONLINE) is online_pool

    assert get_pool(Workload.OFFLINE) is offline_pool
    assert offline_pool is not online_pool


@pytest.fixture(autouse=True)
def clear_lru_cache():
    make_ch_pool.cache_clear()

    yield

    make_ch_pool.cache_clear()
