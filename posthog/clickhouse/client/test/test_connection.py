import pytest

from clickhouse_pool import ChPool

from posthog.clickhouse.client import connection
from posthog.clickhouse.client.connection import (
    ClickHouseCredentials,
    ClickHouseUser,
    RefreshingChPool,
    Workload,
    get_http_client,
    get_pool,
    init_clickhouse_users,
    make_ch_pool,
    set_default_clickhouse_workload_type,
)
from posthog.clickhouse.client.execute import sync_execute


def _file_backed_default(monkeypatch, path, *, fallback="fallback"):
    creds = ClickHouseCredentials(user="default", password=fallback, password_file=str(path))
    monkeypatch.setattr(connection, "__user_dict", {ClickHouseUser.DEFAULT: creds})
    return creds


@pytest.mark.django_db
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
    assert type(online_pool) is ChPool  # a user with no password file keeps a plain, non-refreshing pool
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

    assert online_pool.connection_args["host"] == settings.CLICKHOUSE_HOST
    assert team_pool.connection_args["host"] == "clicky"


def test_read_password_reads_file_fresh_and_stripped(tmp_path):
    token = tmp_path / "token"
    token.write_text("tok-0\n")
    creds = ClickHouseCredentials(user="u", password="fallback", password_file=str(token))

    assert creds.read_password() == "tok-0"

    token.write_text("  tok-1  ")  # a later rotation must be picked up, not cached at construction
    assert creds.read_password() == "tok-1"


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_read_password_falls_back_when_file_unusable(tmp_path, state):
    token = tmp_path / "token"
    if state == "empty":
        token.write_text("")

    creds = ClickHouseCredentials(user="u", password="fallback-secret", password_file=str(token))
    assert creds.read_password() == "fallback-secret"


def test_password_file_env_registers_file_backed_user(monkeypatch, tmp_path):
    token = tmp_path / "cohorts-token"
    token.write_text("cohorts-token-value")
    monkeypatch.setenv("CLICKHOUSE_COHORTS_USER", "cohorts")
    monkeypatch.setenv("CLICKHOUSE_COHORTS_PASSWORD_FILE", str(token))
    monkeypatch.delenv("CLICKHOUSE_COHORTS_PASSWORD", raising=False)

    creds = init_clickhouse_users()[ClickHouseUser.COHORTS]
    assert creds.user == "cohorts"
    assert creds.read_password() == "cohorts-token-value"


def test_file_backed_pool_is_stable_across_credential_rotation(settings, monkeypatch, tmp_path):
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = None
    token = tmp_path / "token"
    token.write_text("tok-0")
    _file_backed_default(monkeypatch, token)

    pool = get_pool(Workload.ONLINE)
    assert isinstance(pool, RefreshingChPool)

    token.write_text("tok-1")  # rotate the projected token in place
    assert get_pool(Workload.ONLINE) is pool
    assert make_ch_pool.cache_info().currsize == 1


def test_refreshing_pool_stamps_current_credential(tmp_path):
    token = tmp_path / "token"
    token.write_text("tok-0")
    pool = RefreshingChPool(
        credential_provider=lambda: token.read_text().strip(),
        host="localhost",
        port=1,
        connections_min=1,
        connections_max=1,
    )

    client = pool.pull()
    assert client.connection.password == "tok-0"
    pool.push(client)

    token.write_text("tok-1")
    client = pool.pull()
    assert client.connection.password == "tok-1"
    pool.push(client)


@pytest.fixture(autouse=True)
def reset_state():
    make_ch_pool.cache_clear()

    yield

    make_ch_pool.cache_clear()
    set_default_clickhouse_workload_type(Workload.ONLINE)
