import json
import time
import base64
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

from posthog.clickhouse.client import connection
from posthog.clickhouse.client.connection import (
    _TOKEN_EXPIRY_LEEWAY_SECONDS,
    ClickHouseChPool,
    ClickHouseCredentials,
    ClickHouseUser,
    RefreshingChPool,
    Workload,
    default_client,
    default_workload_from_settings,
    get_clickhouse_creds,
    get_http_client,
    get_http_kwargs,
    get_pool,
    init_clickhouse_users,
    make_ch_pool,
    set_default_clickhouse_workload_type,
)
from posthog.clickhouse.client.execute import sync_execute

if TYPE_CHECKING:
    from pytest_django.fixtures import Settings


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
    assert type(online_pool) is ClickHouseChPool  # a user with no password file keeps a non-refreshing pool
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


@pytest.mark.parametrize("value,expected", [("ONLINE", Workload.ONLINE), ("OFFLINE", Workload.OFFLINE)])
def test_default_workload_from_settings(settings, value, expected):
    settings.CLICKHOUSE_DEFAULT_WORKLOAD = value

    assert default_workload_from_settings() == expected


@pytest.mark.parametrize("value", ["LOGS", "ENDPOINTS", "DEFAULT", "offline-ish"])
def test_default_workload_from_settings_rejects_other_workloads(settings, value):
    settings.CLICKHOUSE_DEFAULT_WORKLOAD = value

    with pytest.raises(ValueError):
        default_workload_from_settings()


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


@pytest.mark.parametrize("user", [ClickHouseUser.SIGNALS, ClickHouseUser.DEFAULT, ClickHouseUser.ERROR_TRACKING])
def test_signals_readonly_queries_keep_dedicated_credentials_and_offline_host(
    settings: "Settings", monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user: ClickHouseUser
) -> None:
    settings.READONLY_CLICKHOUSE_USER = "shared-readonly"
    settings.READONLY_CLICKHOUSE_PASSWORD = "shared-password"
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = "offline.example.com"
    token = tmp_path / "signals-token"
    token.write_text("signals-token-value")
    monkeypatch.setattr(
        connection,
        "__user_dict",
        {
            ClickHouseUser.SIGNALS: ClickHouseCredentials(user="signals", password="", password_file=str(token)),
            ClickHouseUser.DEFAULT: ClickHouseCredentials(user="default", password="default-password"),
            ClickHouseUser.ERROR_TRACKING: ClickHouseCredentials(user="error_tracking", password="error-password"),
        },
    )

    kwargs = get_http_kwargs(Workload.OFFLINE, readonly=True, ch_user=user)

    if user == ClickHouseUser.SIGNALS:
        assert kwargs == {
            "user": "signals",
            "password": "signals-token-value",
            "host": "offline.example.com",
            "verify": False,
        }
    else:
        assert kwargs == {"user": "shared-readonly", "password": "shared-password"}


def test_native_events_pool_is_separate_from_legacy_pool(settings, monkeypatch):
    from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
    from posthog.models.event.new_events_schema import new_events_cluster_host_scope

    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = "env.example.com"
    host = "native.example.com"
    monkeypatch.setattr("posthog.models.event.new_events_schema.get_instance_setting", lambda key: host)
    settings.CLICKHOUSE_VERIFY = True
    settings.CLICKHOUSE_PER_TEAM_SETTINGS = {}
    legacy = get_pool(Workload.ONLINE, team_id=44)
    native = get_pool(Workload.NEW_EVENTS_CLUSTER, team_id=44)
    assert native is not legacy
    assert native.connection_args["host"] == "native.example.com"
    with new_events_cluster_host_scope():
        assert get_pool(Workload.NEW_EVENTS_CLUSTER, team_id=44) is native
        host = "replacement.example.com"
        pools = []
        run_in_parallel_threads([lambda: pools.append(get_pool(Workload.NEW_EVENTS_CLUSTER, team_id=44))])
        assert pools == [native]
    replacement = get_pool(Workload.NEW_EVENTS_CLUSTER, team_id=44)
    assert replacement is not native
    assert replacement.connection_args["host"] == host


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("team_override", [False, True])
def test_native_events_route_preserves_resolved_credentials(settings, readonly, team_override):
    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = "native.example.com"
    settings.CLICKHOUSE_VERIFY = True
    settings.CLICKHOUSE_PER_TEAM_SETTINGS = (
        {"44": {"host": "legacy.example.com", "user": "team-user", "password": "example"}} if team_override else {}
    )
    settings.READONLY_CLICKHOUSE_USER = "reader"
    settings.READONLY_CLICKHOUSE_PASSWORD = "example-readonly"
    baseline = connection.get_kwargs_for_client(Workload.DEFAULT, team_id=44, readonly=readonly)
    native = connection.get_kwargs_for_client(Workload.NEW_EVENTS_CLUSTER, team_id=44, readonly=readonly)
    assert native == {**baseline, "host": "native.example.com", "verify": True}


def test_native_events_workload_without_host_fails_closed(settings):
    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = None
    with pytest.raises(ValueError, match="Native events ClickHouse host is not configured"):
        get_pool(Workload.NEW_EVENTS_CLUSTER)


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


def _sa_token(exp: int) -> str:
    def _seg(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{_seg({'alg': 'RS256', 'typ': 'JWT'})}.{_seg({'aud': ['clickhouse-auth'], 'exp': exp})}.signature"


@pytest.mark.parametrize(
    "password,token_kind,expect_static",
    [
        pytest.param("static-secret", "expired", True, id="armed-and-expired-uses-static"),
        pytest.param("static-secret", "valid", False, id="armed-and-valid-uses-token"),
        pytest.param("", "expired", False, id="token-only-keeps-expired-token"),
        pytest.param("static-secret", "malformed", False, id="unparseable-token-is-sent"),
        pytest.param("static-secret", "non_dict_payload", False, id="non-dict-payload-is-sent"),
        pytest.param("static-secret", "oversized_exp", False, id="oversized-exp-is-sent"),
        pytest.param("static-secret", "near_expiry", True, id="near-expiry-uses-static"),
    ],
)
def test_read_password_uses_static_only_for_an_armed_user_with_an_expired_token(
    tmp_path, password, token_kind, expect_static
):
    if token_kind == "malformed":
        token = "not-a-jwt"
    elif token_kind == "non_dict_payload":
        payload = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).rstrip(b"=").decode()
        token = f"header.{payload}.signature"
    elif token_kind == "oversized_exp":
        token = _sa_token(10**400)
    elif token_kind == "near_expiry":
        token = _sa_token(int(time.time()) + _TOKEN_EXPIRY_LEEWAY_SECONDS - 1)
    else:
        token = _sa_token(int(time.time()) + (-3600 if token_kind == "expired" else 3600))
    token_file = tmp_path / "token"
    token_file.write_text(token)
    creds = ClickHouseCredentials(user="datawarehouse", password=password, password_file=str(token_file))

    assert creds.read_password() == (password if expect_static else token)


@pytest.mark.parametrize("user", [ClickHouseUser.COHORTS, ClickHouseUser.SIGNALS])
def test_password_file_env_registers_file_backed_user(monkeypatch, tmp_path, user):
    token = tmp_path / "cohorts-token"
    token.write_text("cohorts-token-value")
    monkeypatch.setenv(f"CLICKHOUSE_{user.name}_USER", user.value)
    monkeypatch.setenv(f"CLICKHOUSE_{user.name}_PASSWORD_FILE", str(token))
    monkeypatch.delenv(f"CLICKHOUSE_{user.name}_PASSWORD", raising=False)

    creds = init_clickhouse_users()[user]
    assert creds.user == user.value
    assert creds.read_password() == "cohorts-token-value"


@pytest.mark.parametrize(
    "debug,test,explicit_user,expected_user",
    [
        (False, False, None, None),
        (True, False, None, "signals"),
        (False, True, None, "signals"),
        (True, False, "custom-signals", None),
    ],
)
def test_signals_development_credentials_do_not_mask_deployment_config(
    monkeypatch: pytest.MonkeyPatch, debug: bool, test: bool, explicit_user: str | None, expected_user: str | None
) -> None:
    monkeypatch.setattr(connection.data_stores, "DEBUG", debug)
    monkeypatch.setattr(connection.data_stores, "TEST", test)
    for suffix in ("USER", "PASSWORD", "PASSWORD_FILE"):
        monkeypatch.delenv(f"CLICKHOUSE_SIGNALS_{suffix}", raising=False)
    if explicit_user is not None:
        monkeypatch.setenv("CLICKHOUSE_SIGNALS_USER", explicit_user)

    creds = init_clickhouse_users().get(ClickHouseUser.SIGNALS)
    assert (creds.user if creds else None) == expected_user


@pytest.mark.parametrize("user", [ClickHouseUser.BUSINESS_KNOWLEDGE, ClickHouseUser.SIGNALS])
def test_dedicated_credentials_do_not_fall_back_to_default(monkeypatch, user):
    default_creds = ClickHouseCredentials(user="default", password="default-password")
    monkeypatch.setattr(connection, "__user_dict", {ClickHouseUser.DEFAULT: default_creds})

    with pytest.raises(RuntimeError, match=f"CLICKHOUSE_{user.name}_USER"):
        get_clickhouse_creds(user)


def test_deletion_executor_credentials_do_not_fall_back_to_default(monkeypatch):
    default_creds = ClickHouseCredentials(user="default", password="default-password")
    monkeypatch.setattr(connection, "__user_dict", {ClickHouseUser.DEFAULT: default_creds})

    with pytest.raises(RuntimeError, match="CLICKHOUSE_DELETION_EXECUTOR_USER"):
        get_clickhouse_creds(ClickHouseUser.DELETION_EXECUTOR)


@pytest.mark.parametrize("workload", [Workload.ONLINE, Workload.NEW_EVENTS_CLUSTER])
def test_file_backed_pool_is_stable_across_credential_rotation(settings, monkeypatch, tmp_path, workload):
    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = "native.example.com"
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = None
    token = tmp_path / "token"
    token.write_text("tok-0")
    _file_backed_default(monkeypatch, token)

    pool = get_pool(workload)
    assert isinstance(pool, RefreshingChPool)

    token.write_text("tok-1")  # rotate the projected token in place
    assert get_pool(workload) is pool
    assert make_ch_pool.cache_info().currsize == 1


@pytest.mark.parametrize("workload", [Workload.ONLINE, Workload.NEW_EVENTS_CLUSTER])
def test_get_http_kwargs_reads_file_backed_credential_fresh(settings, monkeypatch, tmp_path, workload):
    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = "native.example.com"
    token = tmp_path / "token"
    token.write_text("tok-0")
    _file_backed_default(monkeypatch, token)

    assert get_http_kwargs(workload)["password"] == "tok-0"

    token.write_text("tok-1")  # a rotation must reach the short-lived HTTP client, not a value cached at build
    assert get_http_kwargs(workload)["password"] == "tok-1"


def test_get_client_from_pool_http_branch_sends_fresh_token(settings, monkeypatch, tmp_path):
    settings.CLICKHOUSE_USE_HTTP = True
    token = tmp_path / "token"
    token.write_text("tok-0")
    _file_backed_default(monkeypatch, token)

    with patch.object(connection, "get_http_client") as mock_http_client:
        connection.get_client_from_pool(Workload.ONLINE)

    # The HTTP dispatch must route through get_http_kwargs so a rotated token reaches the client.
    # Asserting the credential handed to get_http_client, not that the helper was called, keeps this
    # green if the kwargs building is ever inlined.
    assert mock_http_client.call_args.kwargs["password"] == "tok-0"


@pytest.mark.parametrize(
    "kwargs,expected_user,expected_password",
    [
        pytest.param({}, "pod-user", "live-token", id="no-credentials-uses-the-pod-token"),
        pytest.param({"password": "explicit"}, "pod-user", "explicit", id="explicit-password-is-kept"),
        pytest.param({"user": "other"}, "other", "pod-static", id="other-user-never-gets-the-pod-token"),
    ],
)
def test_default_client_sends_the_pod_token_only_without_explicit_credentials(
    settings, tmp_path, kwargs, expected_user, expected_password
):
    token = tmp_path / "token"
    token.write_text("live-token")
    settings.CLICKHOUSE_USER = "pod-user"
    settings.CLICKHOUSE_PASSWORD = "pod-static"
    settings.CLICKHOUSE_PASSWORD_FILE = str(token)

    client = default_client(**kwargs)

    assert (client.connection.user, client.connection.password) == (expected_user, expected_password)


@pytest.mark.parametrize("failure", [None, "missing", "empty"])
def test_refreshing_pool_stamps_current_credential(tmp_path: Path, failure: str | None) -> None:
    token = tmp_path / "token"
    token.write_text("tok-0")
    creds = ClickHouseCredentials(user="signals", password="", password_file=str(token), require_password=True)
    pool = RefreshingChPool(
        credential_provider=creds.read_password,
        host="localhost",
        port=1,
        connections_min=1,
        connections_max=1,
    )

    client = pool.pull()
    assert client.connection.password == "tok-0"
    pool.push(client)

    if failure is not None:
        if failure == "missing":
            token.unlink()
        else:
            token.write_text("")
        for _ in range(3):
            with pytest.raises(RuntimeError, match="signals"):
                with pool.get_client():
                    pytest.fail("Missing credentials must fail closed")

    token.write_text("tok-1")
    client = pool.pull()
    assert client.connection.password == "tok-1"
    pool.push(client)


@pytest.fixture(autouse=True)
def reset_state(settings, monkeypatch):
    make_ch_pool.cache_clear()
    monkeypatch.setattr(
        "posthog.models.event.new_events_schema.get_instance_setting",
        lambda key: settings.CLICKHOUSE_NATIVE_EVENTS_HOST,
    )

    yield

    make_ch_pool.cache_clear()
    set_default_clickhouse_workload_type(Workload.ONLINE)


@pytest.mark.parametrize(
    "registered,ch_user,expected_user,expected_password",
    [
        (True, ClickHouseUser.ALERTS_PLATFORM_LOGS, "alerts_platform_logs", "logs-token"),
        (False, ClickHouseUser.ALERTS_PLATFORM_LOGS, "logs-user", "logs-static"),
        (True, ClickHouseUser.DEFAULT, "logs-user", "logs-static"),
        (True, ClickHouseUser.APP, "logs-user", "logs-static"),
    ],
)
def test_logs_workload_uses_a_named_user_only_when_registered(
    settings, monkeypatch, tmp_path, registered, ch_user, expected_user, expected_password
):
    settings.CLICKHOUSE_LOGS_CLUSTER_USER = "logs-user"
    settings.CLICKHOUSE_LOGS_CLUSTER_PASSWORD = "logs-static"
    default_token = tmp_path / "default-token"
    default_token.write_text("default-token")
    logs_token = tmp_path / "logs-token"
    logs_token.write_text("logs-token")
    users = {
        ClickHouseUser.DEFAULT: ClickHouseCredentials(user="default", password="x", password_file=str(default_token))
    }
    if registered:
        users[ClickHouseUser.ALERTS_PLATFORM_LOGS] = ClickHouseCredentials(
            user="alerts_platform_logs", password="fallback", password_file=str(logs_token)
        )
        users[ClickHouseUser.APP] = ClickHouseCredentials(user="app", password="app-static")
    monkeypatch.setattr(connection, "__user_dict", users)

    kwargs = get_http_kwargs(Workload.LOGS, ch_user=ch_user)

    assert (kwargs["host"], kwargs["user"], kwargs["password"]) == (
        settings.CLICKHOUSE_LOGS_CLUSTER_HOST,
        expected_user,
        expected_password,
    )


@pytest.mark.parametrize(
    "workload,clickhouse_verify,queryservice_verify,expected_verify",
    [
        (Workload.NEW_EVENTS_CLUSTER, False, True, True),
        (Workload.NEW_EVENTS_CLUSTER, True, False, False),
        (Workload.OFFLINE, True, True, True),
    ],
)
def test_http_pool_preserves_existing_verification_policy(
    settings, monkeypatch, workload, clickhouse_verify, queryservice_verify, expected_verify
):
    settings.CLICKHOUSE_NATIVE_EVENTS_HOST = "native.example.com"
    settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST = "offline.example.com"
    settings.CLICKHOUSE_VERIFY = clickhouse_verify
    settings.QUERYSERVICE_VERIFY = queryservice_verify
    settings.CLICKHOUSE_SECURE = True
    settings.CLICKHOUSE_LOGS_CLUSTER_SECURE = True
    settings.CLICKHOUSE_USE_HTTP = True
    monkeypatch.setattr(connection, "_default_workload", Workload.OFFLINE)
    connection._clickhouse_http_pool_mgr.cache_clear()
    try:
        with patch("clickhouse_connect.get_client") as client:
            with connection.get_client_from_pool(workload):
                pass
        manager = client.call_args.kwargs["pool_mgr"]
        assert client.call_args.kwargs["secure"]
        assert manager.connection_pool_kw["cert_reqs"] == ("CERT_REQUIRED" if expected_verify else "CERT_NONE")
    finally:
        connection._clickhouse_http_pool_mgr.cache_clear()
