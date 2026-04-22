import urllib.error
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication

TEST_HTTP_URL = "http://clickhouse-test.internal:8123"


@override_settings(CLICKHOUSE_PERF_TEST_HTTP_URL=TEST_HTTP_URL)
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

    def test_returns_503_when_url_unset(self):
        token = self._make_token(["clickhouse_perf:test_read"])
        with (
            override_settings(CLICKHOUSE_PERF_TEST_HTTP_URL=""),
            patch("posthog.api.query_performance_proxy.urllib.request.urlopen") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert mocked.call_count == 0

    # --- settings suffix is the real guardrail -----------------------------
    #
    # The proxy appends `SETTINGS max_execution_time = 60, readonly = 2` to
    # every submission. Server-side enforcement (readonly=2 pinned in the
    # ClickHouse user's profile + row policies) is what actually keeps writes
    # out — the proxy's job is to make sure those settings always travel
    # with the query. The tests below verify the suffix, and that
    # write-shaped queries are forwarded rather than filtered at the Django
    # layer (so the server can reject them).

    def test_appends_readonly_settings_to_every_request(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.urllib.request.urlopen") as mocked:
            reader = MagicMock()
            reader.read.return_value = b"1\n"
            reader.headers = {
                "X-ClickHouse-Summary": '{"read_rows":"1","read_bytes":"1"}',
                "X-ClickHouse-Query-Id": "qid-test-123",
            }
            mocked.return_value.__enter__.return_value = reader

            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        called_req = mocked.call_args.args[0]
        assert called_req.full_url.startswith(TEST_HTTP_URL)
        assert b"readonly = 2" in called_req.data
        assert b"max_execution_time = 60" in called_req.data

    def test_write_is_forwarded_and_clickhouse_rejection_becomes_502(self):
        # INSERT / ALTER / DROP / etc. are not filtered by the proxy; the
        # ClickHouse user runs with `readonly = 2` and will reject writes.
        # We assert the server's rejection arrives back to the caller as a
        # 502 with the upstream detail intact, proving the proxy stays out of
        # the way and the enforcement is server-side.
        token = self._make_token(["clickhouse_perf:test_read"])

        for write_sql in ("INSERT INTO t VALUES (1)", "ALTER TABLE t DELETE WHERE 1 = 1", "DROP TABLE t"):
            err = urllib.error.HTTPError(
                url=TEST_HTTP_URL,
                code=403,
                msg="Forbidden",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )
            err.read = lambda: b"Cannot execute query in readonly mode"  # type: ignore[method-assign] # ty: ignore[invalid-assignment]

            with patch(
                "posthog.api.query_performance_proxy.urllib.request.urlopen",
                side_effect=err,
            ) as mocked:
                resp = self._post(
                    "/api/query_performance_proxy/execute-test/",
                    token=token,
                    body={"sql": write_sql},
                )

            # The write was forwarded (not filtered at Django).
            assert mocked.call_count == 1, f"{write_sql!r} was not forwarded"
            # And the forwarded body carried the readonly=2 suffix.
            called_req = mocked.call_args.args[0]
            assert b"readonly = 2" in called_req.data
            # And the upstream 403 surfaces as 502 so the caller sees CH's reason.
            assert resp.status_code == 502, f"{write_sql!r} did not 502 ({resp.status_code})"
            assert "readonly" in (resp.json().get("detail") or "")

    def test_clickhouse_unreachable_becomes_502(self):
        token = self._make_token(["clickhouse_perf:test_read"])
        with patch(
            "posthog.api.query_performance_proxy.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 502
        assert "unreachable" in resp.json()["error"]

    # --- happy path --------------------------------------------------------

    def test_test_endpoint_proxies_select(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.urllib.request.urlopen") as mocked:
            reader = MagicMock()
            reader.read.return_value = b"1\n"
            reader.headers = {
                "X-ClickHouse-Summary": '{"read_rows":"1","read_bytes":"1"}',
                "X-ClickHouse-Query-Id": "qid-test-123",
            }
            mocked.return_value.__enter__.return_value = reader

            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        payload = resp.json()
        assert payload["result"] == "1\n"
        assert payload["rows_read"] == 1
        assert payload["bytes_read"] == 1
        assert payload["query_id"] == "qid-test-123"
        assert isinstance(payload["elapsed_ms"], int | float)
