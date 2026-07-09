from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from posthog.api.query_performance_proxy import MAX_SQL_LENGTH, ExecuteTestClusterRequestSerializer
from posthog.clickhouse.test_cluster_client import (
    TestClusterNotConfigured,
    TestClusterQueryError,
    TestClusterResult,
    execute_on_test_cluster,
)
from posthog.models.oauth import OAuthAccessToken, OAuthApplication


class TestExecuteTestClusterRequestSerializer(SimpleTestCase):
    def test_missing_sql_is_invalid(self):
        serializer = ExecuteTestClusterRequestSerializer(data={})
        assert not serializer.is_valid()
        assert "sql" in serializer.errors

    def test_oversized_sql_is_invalid(self):
        serializer = ExecuteTestClusterRequestSerializer(data={"sql": "S" * (MAX_SQL_LENGTH + 1)})
        assert not serializer.is_valid()
        assert serializer.errors["sql"][0].code == "max_length"


class BaseQueryPerformanceProxyTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_query_perf_proxy_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="clickhouse_test_cluster_perf:read",
        )

    def _post_execute(self, data: dict):
        return self.client.post(
            "/api/query_performance_proxy/execute-test/",
            data,
            format="json",
            headers={"authorization": f"Bearer {self.access_token.token}"},
        )


class TestExecuteTestCluster(BaseQueryPerformanceProxyTest):
    def test_returns_503_when_test_cluster_unconfigured(self):
        with self.settings(CLICKHOUSE_TEST_CLUSTER_HOST=""):
            response = self._post_execute({"sql": "SELECT 1"})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    def test_invalid_request_body_returns_400(self):
        response = self._post_execute({})
        assert response.status_code == 400

    @patch("posthog.api.query_performance_proxy.execute_on_test_cluster")
    def test_forwards_sql_and_returns_rows_with_stats(self, execute):
        execute.return_value = TestClusterResult(
            result=[[1, "a"]], query_id="qid-1", elapsed_ms=12.5, rows_read=100, bytes_read=2048
        )
        response = self._post_execute({"sql": "SELECT team_id, lc_kind FROM query_log_archive LIMIT 1"})
        assert response.status_code == 200
        body = response.json()
        assert body["result"] == [[1, "a"]]
        assert body["query_id"] == "qid-1"
        assert body["elapsed_ms"] == 12.5
        assert body["rows_read"] == 100
        assert body["bytes_read"] == 2048
        assert body["rows_returned"] == 1
        execute.assert_called_once_with("SELECT team_id, lc_kind FROM query_log_archive LIMIT 1")

    @patch("posthog.api.query_performance_proxy.execute_on_test_cluster")
    def test_clickhouse_error_returns_400_with_message(self, execute):
        execute.side_effect = TestClusterQueryError("Syntax error: failed at position 1")
        response = self._post_execute({"sql": "SELEC 1"})
        assert response.status_code == 400
        assert "Syntax error" in response.json()["detail"]


class TestExecuteOnTestCluster(TestCase):
    def test_raises_not_configured_when_host_unset(self):
        with self.settings(CLICKHOUSE_TEST_CLUSTER_HOST=""):
            with self.assertRaises(TestClusterNotConfigured):
                execute_on_test_cluster("SELECT 1")

    @patch("posthog.clickhouse.test_cluster_client.SyncClient")
    def test_builds_readonly_client_and_canonicalizes_rows(self, client_cls):
        instance = client_cls.return_value
        instance.execute.return_value = [(1, "x")]
        instance.last_query = MagicMock(elapsed=0.0125, progress=MagicMock(rows=100, bytes=2048))
        with self.settings(CLICKHOUSE_TEST_CLUSTER_HOST="test-ch", CLICKHOUSE_TEST_CLUSTER_USER="autoresearch"):
            out = execute_on_test_cluster("SELECT 1")
        assert out.result == [[1, "x"]]
        assert out.query_id is not None and out.query_id.startswith("pulse-autoresearch-")
        assert out.elapsed_ms == 12.5
        assert out.rows_read == 100
        assert out.bytes_read == 2048
        _, kwargs = client_cls.call_args
        assert kwargs["user"] == "autoresearch"
        assert kwargs["settings"]["readonly"] == 1
        assert kwargs["settings"]["max_execution_time"] == 60
        assert kwargs["settings"]["max_result_rows"] == 10_000
        instance.disconnect.assert_called_once()

    @patch("posthog.clickhouse.test_cluster_client.SyncClient")
    def test_driver_error_raises_query_error_and_disconnects(self, client_cls):
        instance = client_cls.return_value
        instance.execute.side_effect = Exception("DB::Exception: Syntax error")
        with self.settings(CLICKHOUSE_TEST_CLUSTER_HOST="test-ch"):
            with self.assertRaises(TestClusterQueryError):
                execute_on_test_cluster("SELEC 1")
        instance.disconnect.assert_called_once()
