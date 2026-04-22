from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.errors import InternalCHQueryError
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

TEST_HOST = "clickhouse-test.internal"


@override_settings(CLICKHOUSE_PERF_TEST_HOST=TEST_HOST)
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

    def _make_token(self, scopes: list[str]) -> str:
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token=f"pha_test_{'_'.join(scopes).replace(':', '_')}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join(scopes),
            scoped_teams=[self.team.id],
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
            override_settings(CLICKHOUSE_PERF_TEST_HOST=""),
            patch("posthog.api.query_performance_proxy.sync_execute") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert mocked.call_count == 0

    # --- settings are the real guardrail -----------------------------------
    #
    # The proxy passes `readonly = 2` + `max_execution_time = 60` on every
    # submission. Server-side enforcement (the ClickHouse user's profile
    # pinning `readonly = 2` + row policies) is what actually keeps writes
    # out — the proxy's job is to make sure those settings always travel
    # with the query. The tests below verify the settings are set and that
    # write-shaped queries are forwarded rather than filtered at the Django
    # layer (so the server can reject them).

    def test_passes_readonly_and_timeout_settings_on_every_request(self):
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
        assert passed_settings["readonly"] == 2
        assert passed_settings["max_execution_time"] == 60
        # sync_execute is called in read-only elevation mode (for workload routing).
        assert mocked.call_args.kwargs.get("readonly") is True
        # And against a SyncClient pointed at the configured host.
        client = mocked.call_args.kwargs["sync_client"]
        assert client.connection.hosts[0][0] == TEST_HOST

    def test_write_is_forwarded_and_clickhouse_rejection_becomes_502(self):
        # INSERT / ALTER / DROP / etc. are not filtered by the proxy; the
        # ClickHouse user runs with `readonly = 2` and will reject writes.
        # We assert the server's rejection arrives back to the caller as a
        # 502 with the upstream detail intact, proving the proxy stays out
        # of the way and enforcement is server-side.
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
            # The CH error surfaces as 502 with upstream detail + code.
            payload = resp.json()
            assert resp.status_code == 502, f"{write_sql!r} did not 502 ({resp.status_code})"
            assert "readonly" in payload["detail"]
            assert payload["code"] == 164

    def test_clickhouse_connection_failure_becomes_502(self):
        token = self._make_token(["clickhouse_perf:test_read"])
        with patch(
            "posthog.api.query_performance_proxy.sync_execute",
            side_effect=ConnectionRefusedError("refused"),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 502
        assert "unreachable" in resp.json()["error"]

    # --- happy path --------------------------------------------------------

    def test_test_endpoint_proxies_select_and_serializes_rows(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.sync_execute") as mocked:
            mocked.return_value = [(1, "a"), (2, None)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT id, name FROM events"},
            )

        assert resp.status_code == 200, resp.content
        payload = resp.json()
        # Rows are TSV-encoded to match the old HTTP interface; None → \N so
        # autoresearch's result diffing stays stable.
        assert payload["result"] == "1\ta\n2\t\\N\n"
        assert payload["rows_read"] == 2
        assert payload["bytes_read"] is None
        assert isinstance(payload["elapsed_ms"], int | float)
