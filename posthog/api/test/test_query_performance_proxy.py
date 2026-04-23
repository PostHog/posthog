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
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])
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
        # Must refuse regardless of how `CLICKHOUSE_TEST_CLUSTER_HOST` happens
        # to be set — DEBUG is the hard gate against accidental prod exposure.
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])
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

    def test_passes_duration_cap_and_readonly_on_every_request(self):
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        passed_settings = mocked.call_args.kwargs["settings"]
        assert passed_settings["readonly"] == 2
        assert passed_settings["max_execution_time"] == 5 * 60
        assert mocked.call_args.kwargs.get("readonly") is True
        client = mocked.call_args.kwargs["sync_client"]
        assert client.connection.hosts[0][0] == TEST_HOST

    def test_write_is_forwarded_and_clickhouse_rejection_becomes_502(self):
        # Writes aren't filtered at Django; the CH user's `readonly = 2` is
        # the enforcer. Assert the rejection propagates as a 502 with just
        # the CH error code (no upstream message — CodeQL-flagged exposure).
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])

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

            assert mocked.call_count == 1, f"{write_sql!r} was not forwarded"
            payload = resp.json()
            assert resp.status_code == 502, f"{write_sql!r} did not 502 ({resp.status_code})"
            assert payload["code"] == 164
            assert "detail" not in payload
            assert "readonly" not in str(payload)

    def test_clickhouse_query_error_does_not_leak_exception_text(self):
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])
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
        # Connection errors can embed host / port / cert internals; verify
        # only a generic message makes it back to the caller.
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])
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
        token = self._make_token(["clickhouse_test_cluster_perf:test_read"])

        # rows_read / bytes_read come from the driver's `last_query.profile_info`,
        # so patch `SyncClient` to plant the counters.
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
        assert payload["result"] == [[1, "a"], [2, None]]
        assert payload["rows_read"] == 987654
        assert payload["bytes_read"] == 12345678
        assert payload["rows_returned"] == 2
        assert isinstance(payload["elapsed_ms"], int | float)

    # --- token scoping -----------------------------------------------------

    def test_scoped_teams_token_for_another_team_can_still_reach_endpoint(self):
        # The endpoint is not URL-team-nested, so `scoped_teams` has no URL
        # team to validate against — a token scoped to a different team must
        # still be accepted. Guards against a regression where the proxy
        # started rejecting scoped_teams tokens entirely.
        other_team_token = self._make_token(["clickhouse_test_cluster_perf:test_read"], scoped_teams=[self.team.id + 999])

        with patch("posthog.api.query_performance_proxy.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=other_team_token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        assert mocked.call_count == 1
