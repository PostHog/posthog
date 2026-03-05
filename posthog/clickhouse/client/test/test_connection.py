import pytest

from posthog.clickhouse.client.connection import (
    Workload,
    get_http_client,
    get_pool,
    make_ch_pool,
    set_default_clickhouse_workload_type,
)
from posthog.clickhouse.client.execute import sync_execute


def test_insert_with_http_client():
    sync_execute("DROP TABLE IF EXISTS _test_http_insert")
    sync_execute("CREATE TABLE _test_http_insert (id UInt64) ENGINE = Memory")
    try:
        with get_http_client() as client:
            result = sync_execute(
                "INSERT INTO _test_http_insert SELECT number FROM numbers(3)",
                sync_client=client,
            )
            assert result == 3
    finally:
        sync_execute("DROP TABLE IF EXISTS _test_http_insert")


def test_connection_pool_creation_without_offline_cluster(settings):
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = None

    online_pool = get_pool(Workload.ONLINE)
    assert get_pool(Workload.ONLINE) is online_pool
    assert get_pool(Workload.OFFLINE) is online_pool
    assert get_pool(Workload.DEFAULT) is online_pool


def test_connection_pool_creation_with_offline_cluster(settings):
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = "ch-offline.example.com"

    online_pool = get_pool(Workload.ONLINE)
    offline_pool = get_pool(Workload.OFFLINE)
    assert get_pool(Workload.ONLINE) is online_pool
    assert get_pool(Workload.DEFAULT) is online_pool

    assert get_pool(Workload.OFFLINE) is offline_pool
    assert offline_pool is not online_pool

    set_default_clickhouse_workload_type(Workload.OFFLINE)
    assert get_pool(Workload.DEFAULT) is offline_pool


def test_connection_pool_creation_with_team_id(settings):
    settings.CLICKHOUSE_PER_TEAM_SETTINGS = {}

    online_pool = get_pool(Workload.DEFAULT)
    assert get_pool(Workload.DEFAULT) is online_pool
    assert get_pool(Workload.DEFAULT, team_id=2) is online_pool
    assert get_pool(Workload.DEFAULT, team_id=None) is online_pool

    settings.CLICKHOUSE_PER_TEAM_SETTINGS = {"2": {"host": "clicky", "user": "default"}}
    team_pool = get_pool(Workload.DEFAULT, team_id=2)
    assert get_pool(Workload.DEFAULT) is online_pool
    assert get_pool(Workload.DEFAULT) is not team_pool
    assert get_pool(Workload.DEFAULT, team_id=2) is team_pool
    assert get_pool(Workload.DEFAULT, team_id=3) is online_pool

    assert online_pool.connection_args["host"] == "localhost"
    assert team_pool.connection_args["host"] == "clicky"


@pytest.fixture(autouse=True)
def reset_state():
    make_ch_pool.cache_clear()

    yield

    make_ch_pool.cache_clear()
    set_default_clickhouse_workload_type(Workload.ONLINE)
