"""Integration tests for the `autoresearch` ClickHouse user enforcement.

These tests exercise the actual CH server configured by
``docker/clickhouse/users-dev.xml`` and
``docker/clickhouse/docker-entrypoint-initdb.d/autoresearch-row-policies.sql``
— they confirm that:

- Non-granted table functions (``url``, ``executable``, ``s3``, ...) are
  rejected at the CH authz layer (code 497 ACCESS_DENIED) without any
  SQL-parsing in the Django proxy.
- ``readonly=2`` on the profile is pinned so the client can't override it.
- Writes are rejected.
- The ``system.query_log`` row policy hides cross-user queries.

They connect via ``settings.CLICKHOUSE_TEST_CLUSTER_*`` — which points at
the same local CH container that ``users-dev.xml`` provisions, both in
dev (via ``bin/start``) and in CI (via ``ci-backend.yml``). They **fail**
(not skip) if the autoresearch user isn't reachable: a silent skip would
turn the "SQL safety is CH-enforced" story into unverified wishful
thinking.
"""

from __future__ import annotations

import pytest

from django.conf import settings

from clickhouse_driver import (
    Client as SyncClient,
    errors as ch_errors,
)

# CH error codes we assert on.
CH_ACCESS_DENIED = 497
CH_READONLY = 164
# `file()` with an absolute path outside user_files_path is rejected by CH's
# path check (291) BEFORE the authz grant check fires. For the autoresearch
# user both are acceptable refusals — the data never reaches the caller.
CH_PATH_OUTSIDE_USER_FILES = 291


def _assert_test_cluster_configured() -> None:
    """If the test cluster isn't reachable, fail — don't skip.

    These tests are the load-bearing proof that the CH-side enforcement
    (grants + row policy + readonly=2 profile constraint) actually works.
    A silent skip when ``bin/start`` isn't running or CI's CH container
    didn't come up turns them into a false-green: the "SQL safety" story
    would be unverified while the run still reports success. Forcing the
    operator to have a reachable CH (dev or CI) keeps them honest.
    """
    if not settings.CLICKHOUSE_TEST_CLUSTER_HOST or not settings.CLICKHOUSE_TEST_CLUSTER_USER:
        pytest.fail(
            "CLICKHOUSE_TEST_CLUSTER_HOST / _USER not configured — run `bin/start` locally "
            "(or set the env vars in CI) before running this test."
        )


@pytest.fixture(scope="module")
def autoresearch_client() -> SyncClient:
    """SyncClient as the autoresearch user (settings.CLICKHOUSE_TEST_CLUSTER_*)."""
    _assert_test_cluster_configured()
    client = SyncClient(
        host=settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        database=settings.CLICKHOUSE_TEST_CLUSTER_DATABASE or "default",
        user=settings.CLICKHOUSE_TEST_CLUSTER_USER,
        password=settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        secure=settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        ca_certs=settings.CLICKHOUSE_TEST_CLUSTER_CA,
        verify=settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
        connect_timeout=2,
    )
    try:
        current = client.execute("SELECT currentUser()")
    except Exception as e:
        pytest.fail(f"autoresearch CH user unreachable ({e!r}) — ensure CH is up and `autoresearch` user exists")
    expected = settings.CLICKHOUSE_TEST_CLUSTER_USER
    assert current == [(expected,)], f"unexpected currentUser(): {current!r} (expected {expected!r})"
    return client


@pytest.fixture(scope="module")
def default_client() -> SyncClient:
    """SyncClient as the regular CH user for row-policy cross-user checks.

    Uses ``settings.CLICKHOUSE_*`` creds (not the test-cluster vars) because
    this fixture intentionally talks to CH as a _different_ user than
    autoresearch to generate rows the row policy should hide. Pinned to the
    ``default`` database since this test only touches ``system.*`` tables.
    """
    client = SyncClient(
        host=settings.CLICKHOUSE_HOST,
        database="default",
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
        ca_certs=settings.CLICKHOUSE_CA,
        verify=settings.CLICKHOUSE_VERIFY,
        connect_timeout=2,
    )
    try:
        client.execute("SELECT 1")
    except Exception as e:
        pytest.fail(f"regular CH user unreachable ({e!r}) — ensure CH is up")
    if settings.CLICKHOUSE_USER == settings.CLICKHOUSE_TEST_CLUSTER_USER:
        # Row-policy test is meaningful only when the two clients are
        # different users — otherwise we can't observe "hides other users".
        # This is a misconfigured env, not a skippable condition.
        pytest.fail("regular CH user matches autoresearch user; row-policy cross-user check can't be verified")
    return client


# --- table-function blocks ---------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM url('http://example.com/', CSV, 'x String') LIMIT 1",
        "SELECT * FROM s3('https://example.com/x.csv', 'CSV', 'x String') LIMIT 1",
        # Relative file path so the grant check fires (absolute paths outside
        # user_files_path get rejected by CH's path check first — still a
        # refusal but from a different layer).
        "SELECT * FROM file('foo.csv', 'CSV', 'x String') LIMIT 1",
        "SELECT * FROM remote('example.com:9000', default.x) LIMIT 1",
        "SELECT * FROM mysql('host:3306', 'db', 't', 'u', 'p') LIMIT 1",
        "SELECT * FROM postgresql('host', 'db', 't', 'u', 'p') LIMIT 1",
        "SELECT * FROM executable('whoami', CSV, 'x String') LIMIT 1",
    ],
)
def test_dangerous_table_functions_are_rejected(autoresearch_client: SyncClient, sql: str) -> None:
    # Accept either 497 (grant check — the primary enforcement) or 291 (path
    # restriction for `file()` with absolute paths). Both are hard refusals
    # at the CH server with no data leaked to the caller.
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute(sql)
    assert exc_info.value.code in (CH_ACCESS_DENIED, CH_PATH_OUTSIDE_USER_FILES), (
        f"unexpected code for {sql!r}: {exc_info.value!r}"
    )


# --- readonly enforcement ----------------------------------------------------


def test_insert_rejected(autoresearch_client: SyncClient) -> None:
    # Target system.query_log (always exists; we have SELECT grant but not
    # INSERT) rather than `events` so the test doesn't depend on the target
    # DB having been migrated.
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute("INSERT INTO system.query_log SELECT * FROM system.query_log LIMIT 0")
    # Could be ACCESS_DENIED (no INSERT grant) or READONLY (profile). Either
    # is fine; what matters is that writes don't reach the table.
    assert exc_info.value.code in (CH_ACCESS_DENIED, CH_READONLY), (
        f"INSERT should have been blocked, got code {exc_info.value.code}"
    )


def test_client_cannot_override_readonly(autoresearch_client: SyncClient) -> None:
    # readonly=0 would lift all write restrictions — the profile's
    # <constraints><readonly/> element pins it at 2 so the override
    # is refused server-side.
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute("SELECT 1 SETTINGS readonly=0")
    assert exc_info.value.code == CH_READONLY


# --- positive paths ----------------------------------------------------------


def test_whitelisted_select_works(autoresearch_client: SyncClient) -> None:
    # Target system.query_log since it's always present; the events /
    # persons / sessions grants are exercised implicitly in CI once
    # migrations populate the test DB, but we don't want this test to
    # depend on that — the point here is that a whitelisted table works.
    result = autoresearch_client.execute("SELECT count() FROM system.query_log")
    assert isinstance(result, list) and len(result) == 1


def test_explain_select_works(autoresearch_client: SyncClient) -> None:
    # EXPLAIN inherits privileges from the underlying SELECT — no extra
    # grant needed. Regression guard in case a future CH version changes that.
    result = autoresearch_client.execute("EXPLAIN SELECT count() FROM system.query_log")
    assert isinstance(result, list) and len(result) > 0


def test_query_log_readable(autoresearch_client: SyncClient) -> None:
    # Smoke: autoresearch has SELECT on system.query_log. We don't assert on
    # row count because logs flush asynchronously; the important thing is
    # that the query itself doesn't get rejected.
    autoresearch_client.execute("SELECT count() FROM system.query_log")


# --- row policy on system.query_log -----------------------------------------


def test_query_log_row_policy_hides_other_users(autoresearch_client: SyncClient, default_client: SyncClient) -> None:
    # Kick off a query as each user, flush logs, then assert autoresearch
    # only sees its own rows while the other user sees at least its own.
    autoresearch_client.execute("SELECT 'autoresearch-row-policy-probe' AS marker")
    default_client.execute("SELECT 'default-row-policy-probe' AS marker")
    default_client.execute("SYSTEM FLUSH LOGS")

    as_autoresearch = autoresearch_client.execute("SELECT DISTINCT initial_user FROM system.query_log")
    as_default = default_client.execute("SELECT DISTINCT initial_user FROM system.query_log")

    autoresearch_users = {row[0] for row in as_autoresearch}
    default_users = {row[0] for row in as_default}

    expected_autoresearch_user = settings.CLICKHOUSE_TEST_CLUSTER_USER
    assert autoresearch_users == {expected_autoresearch_user}, (
        f"row policy on system.query_log leaked other users: {autoresearch_users}"
    )
    assert settings.CLICKHOUSE_USER in default_users, (
        f"regular CH user should see its own rows at minimum: {default_users}"
    )
