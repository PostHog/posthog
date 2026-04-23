from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from posthog.errors import InternalCHQueryError
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

TEST_HOST = "clickhouse-test.internal"


@override_settings(CLICKHOUSE_TEST_CLUSTER_HOST=TEST_HOST, DEBUG=True)
class TestQueryPerformanceProxyViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.oauth_app = OAuthApplication.objects.create(
            name="Test query-perf App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )
        self.client.logout()

    def _make_token(self, scopes: list[str], *, scoped_teams: list[int] | None = None) -> str:
        team_scope = [self.team.id] if scoped_teams is None else scoped_teams
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token=f"pha_test_{'_'.join(scopes).replace(':', '_')}_{'_'.join(str(t) for t in team_scope)}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join(scopes),
            scoped_teams=team_scope,
        )
        return token.token

    def _post(self, path: str, *, token: str, body: dict) -> "object":
        return self.client.post(
            path,
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    # --- auth --------------------------------------------------------------

    def test_requires_token(self):
        resp = self.client.post(
            "/api/query_performance_proxy/execute-test/",
            {"sql": "SELECT 1"},
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_rejects_token_without_test_scope(self):
        token = self._make_token(["query:read"])
        resp = self._post(
            "/api/query_performance_proxy/execute-test/",
            token=token,
            body={"sql": "SELECT 1"},
        )
        assert resp.status_code == 403

    # --- config handling ---------------------------------------------------

    def test_returns_503_when_host_unset(self):
        token = self._make_token(["clickhouse_perf:test_read"])
        with (
            override_settings(CLICKHOUSE_TEST_CLUSTER_HOST=""),
            patch("posthog.api.query_performance_proxy.sync_execute") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert mocked.call_count == 0

    def test_returns_503_when_debug_unset(self):
        # The endpoint is dev-only. Even with a valid token and a configured
        # test cluster host, it must refuse when DEBUG is False so a
        # misconfigured production deploy can't expose ClickHouse.
        token = self._make_token(["clickhouse_perf:test_read"])
        with (
            override_settings(DEBUG=False),
            patch("posthog.api.query_performance_proxy.sync_execute") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert "DEBUG" in resp.json()["error"]
        assert mocked.call_count == 0

    # --- settings are the real guardrail -----------------------------------
    #
    # The proxy forces `readonly = 2`, `max_execution_time`, `max_memory_usage`,
    # `max_result_rows`, `max_result_bytes`, and `result_overflow_mode = "throw"`
    # on every submission. Server-side enforcement (the ClickHouse user's
    # profile pinning `readonly = 2` + row policies) is what will ultimately
    # keep writes out — the proxy's job is to make sure those caps always
    # travel with the query. Tests below verify the caps are set and that
    # write-shaped queries are forwarded rather than filtered at the Django
    # layer (so the server can reject them).

    def test_passes_resource_caps_on_every_request(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        passed_settings = mocked.call_args.kwargs["settings"]
        # Writes are blocked via readonly; overflow is hard-fail so the agent
        # must narrow the query rather than silently truncate.
        assert passed_settings["readonly"] == 2
        assert passed_settings["max_execution_time"] == 10 * 60
        assert passed_settings["max_memory_usage"] == 256 * 1024**3
        assert passed_settings["max_result_rows"] == 100_000_000
        assert passed_settings["max_result_bytes"] == 100 * 1024**3
        assert passed_settings["result_overflow_mode"] == "throw"
        # sync_execute is called in read-only elevation mode (for workload routing).
        assert mocked.call_args.kwargs.get("readonly") is True
        # And against a SyncClient pointed at the configured host.
        client = mocked.call_args.kwargs["sync_client"]
        assert client.connection.hosts[0][0] == TEST_HOST

    def test_write_is_forwarded_and_clickhouse_rejection_becomes_502(self):
        # INSERT / ALTER / DROP / etc. are not filtered by the proxy; the
        # ClickHouse user runs with `readonly = 2` and will reject writes.
        # We assert the server's rejection arrives back to the caller as a
        # 502 carrying the CH error code (not the upstream message — that
        # would be an exception-data-exposure path flagged by CodeQL).
        token = self._make_token(["clickhouse_perf:test_read"])

        for write_sql in ("INSERT INTO t VALUES (1)", "ALTER TABLE t DELETE WHERE 1 = 1", "DROP TABLE t"):
            with patch(
                "posthog.api.query_performance_proxy.sync_execute",
                side_effect=InternalCHQueryError("Cannot execute query in readonly mode", code=164),
            ) as mocked:
                resp = self._post(
                    "/api/query_performance_proxy/execute-test/",
                    token=token,
                    body={"sql": write_sql},
                )

            # The write was forwarded (not filtered at Django).
            assert mocked.call_count == 1, f"{write_sql!r} was not forwarded"
            payload = resp.json()
            assert resp.status_code == 502, f"{write_sql!r} did not 502 ({resp.status_code})"
            assert payload["code"] == 164
            # Upstream message must not be echoed to the caller.
            assert "detail" not in payload
            assert "readonly" not in str(payload)

    def test_clickhouse_query_error_does_not_leak_exception_text(self):
        # ClickHouse exception messages embed a C++ stack trace and can carry
        # data-shaped details. CodeQL flagged returning any of this text as
        # information exposure, so the response only carries the CH error
        # code — the full exception is logged server-side for operators.
        token = self._make_token(["clickhouse_perf:test_read"])
        msg = (
            "Code: 62. DB::Exception: Syntax error near 'FROOM'.\n"
            "Stack trace (when copying this message, always include the lines below):\n"
            "0. DB::Exception::Exception() @ 0xdeadbeef in /usr/bin/clickhouse\n"
            "1. DB::parseQuery() @ 0xcafef00d in /usr/bin/clickhouse\n"
        )
        with patch(
            "posthog.api.query_performance_proxy.sync_execute",
            side_effect=InternalCHQueryError(msg, code=62),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT * FROOM events"},
            )

        payload = resp.json()
        assert resp.status_code == 502
        assert payload == {"error": "clickhouse query failed", "code": 62}
        assert "FROOM" not in str(payload)
        assert "Stack trace" not in str(payload)
        assert "0xdeadbeef" not in str(payload)

    def test_clickhouse_connection_failure_does_not_leak_exception_detail(self):
        # A raw ConnectionRefusedError (or DNS / TLS failure) can embed
        # host / port / cert internals. We log the full exception server
        # side and return only a generic "unreachable" message.
        token = self._make_token(["clickhouse_perf:test_read"])
        with patch(
            "posthog.api.query_performance_proxy.sync_execute",
            side_effect=ConnectionRefusedError("refused: 10.0.0.42:9000 (internal-secret-host)"),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        payload = resp.json()
        assert resp.status_code == 502
        assert payload == {"error": "clickhouse unreachable"}
        assert "10.0.0.42" not in str(payload)
        assert "internal-secret-host" not in str(payload)

    # --- happy path --------------------------------------------------------

    def test_test_endpoint_returns_rows_as_native_json(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        # `rows_read` / `bytes_read` are pulled from the native driver's
        # `client.last_query.profile_info` so they reflect CH's view of the
        # query (rows scanned, bytes scanned) — not the number of rows the
        # caller got back. Patch the SyncClient so `profile_info` is set.
        profile = MagicMock(rows=987654, bytes=12345678)
        fake_client = MagicMock()
        fake_client.last_query.profile_info = profile

        with (
            patch("posthog.api.query_performance_proxy.SyncClient", return_value=fake_client),
            patch("posthog.api.query_performance_proxy.sync_execute", return_value=[(1, "a"), (2, None)]),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT id, name FROM events"},
            )

        assert resp.status_code == 200, resp.content
        payload = resp.json()
        # Rows come back as native JSON — no TSV escaping, nulls stay as null.
        # Tuples from clickhouse-driver serialize as lists through DRF's JSON
        # renderer.
        assert payload["result"] == [[1, "a"], [2, None]]
        # rows_read / bytes_read are CH's scan-side counters, not output size.
        assert payload["rows_read"] == 987654
        assert payload["bytes_read"] == 12345678
        # rows_returned is the output row count — useful for the agent to
        # compare against rows_read as a scan-efficiency proxy.
        assert payload["rows_returned"] == 2
        assert isinstance(payload["elapsed_ms"], int | float)

    # --- token scoping -----------------------------------------------------

    def test_scoped_teams_token_for_another_team_can_still_reach_endpoint(self):
        # The proxy is not URL-team-nested: the test cluster has no per-team
        # structure and access is gated by the OAuth scope + DEBUG + CH user's
        # readonly profile. A token scoped to a different team must still be
        # accepted (the endpoint opts out of the generic project-scope check).
        # This is the regression we care about — an earlier version of this
        # PR took a hammer to `permissions.check_team_and_org_permissions`
        # that weakened every INTERNAL endpoint.
        other_team_token = self._make_token(["clickhouse_perf:test_read"], scoped_teams=[self.team.id + 999])

        with patch("posthog.api.query_performance_proxy.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=other_team_token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        assert mocked.call_count == 1
