from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.api.query_performance_proxy import _validate_readonly_sql
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

TEST_HTTP_URL = "http://clickhouse-test.internal:8123"


class TestValidateReadonlySql(APIBaseTest):
    def test_accepts_select(self):
        assert _validate_readonly_sql("SELECT 1") is None

    def test_accepts_with_cte(self):
        assert _validate_readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x") is None

    def test_accepts_explain(self):
        assert _validate_readonly_sql("EXPLAIN SELECT 1") is None

    def test_accepts_lower_case(self):
        assert _validate_readonly_sql("select 1") is None

    def test_strips_comments_and_leading_whitespace(self):
        sql = """
        -- a leading comment
        /* block
           comment */
        SELECT 1
        """
        assert _validate_readonly_sql(sql) is None

    def test_rejects_insert(self):
        err = _validate_readonly_sql("INSERT INTO t VALUES (1)")
        assert err is not None
        assert "read-only" in err.message

    def test_rejects_update(self):
        err = _validate_readonly_sql("UPDATE t SET x = 1")
        assert err is not None

    def test_rejects_delete(self):
        err = _validate_readonly_sql("DELETE FROM t WHERE id = 1")
        assert err is not None

    def test_rejects_empty(self):
        err = _validate_readonly_sql("   \n  ")
        assert err is not None

    def test_rejects_statement_hidden_behind_comments(self):
        # `-- SELECT 1` is stripped; the remainder must still be a SELECT/WITH/EXPLAIN.
        err = _validate_readonly_sql("-- SELECT 1\nDROP TABLE t")
        assert err is not None


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

    # --- validation --------------------------------------------------------

    def test_rejects_insert_with_400_and_no_upstream_call(self):
        token = self._make_token(["clickhouse_perf:test_read"])
        with patch("posthog.api.query_performance_proxy.urllib.request.urlopen") as mocked:
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "INSERT INTO t VALUES (1)"},
            )
        assert resp.status_code == 400
        assert mocked.call_count == 0

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

    # --- happy path (proxy call mocked) ------------------------------------

    def test_test_endpoint_proxies_select(self):
        token = self._make_token(["clickhouse_perf:test_read"])

        with patch("posthog.api.query_performance_proxy.urllib.request.urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = b"1\n"
            mocked.return_value.__enter__.return_value.headers = {
                "X-ClickHouse-Summary": '{"read_rows":"1","read_bytes":"1"}',
                "X-ClickHouse-Query-Id": "qid-test-123",
            }
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

        # Verify we dispatched to the test cluster URL.
        called_req = mocked.call_args.args[0]
        assert called_req.full_url.startswith(TEST_HTTP_URL)
        assert b"readonly = 2" in called_req.data
