from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.api.observability import _joinable_trace_id_predicate_hogql


def test_joinable_trace_id_predicate_hogql_contains_trace_id():
    sql = _joinable_trace_id_predicate_hogql()
    assert "trace_id" in sql
    assert "replaceRegexpAll" in sql


class TestObservabilitySignalSnapshotApi(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @patch("posthog.api.observability.execute_hogql_query")
    @patch("posthog.api.observability.TraceSpansQueryRunner")
    def test_signal_snapshot_response_shape(self, mock_runner_cls, mock_execute):
        qdr = MagicMock()
        qdr.date_from.return_value = datetime(2025, 12, 16, 0, 0, tzinfo=UTC)
        qdr.date_to.return_value = datetime(2025, 12, 17, 0, 0, tzinfo=UTC)
        mock_runner_cls.return_value.query_date_range = qdr

        def exec_side_effect(query, **_kwargs):
            q = str(query).strip()
            if "count() AS logs_total" in q:
                return MagicMock(error=None, results=[(5, 2)])
            if "GROUP BY service_name" in q:
                return MagicMock(
                    error=None,
                    results=[("svc-logs", 3), ("svc-both", 2)],
                )
            if "FROM posthog.trace_spans" in q:
                return MagicMock(error=None, results=[("svc-both",), ("svc-trace",)])
            if "SELECT DISTINCT trace_id" in q:
                return MagicMock(error=None, results=[("abcd",), ("efgh",)])
            return MagicMock(error=None, results=[])

        mock_execute.side_effect = exec_side_effect

        response = self.client.post(
            f"/api/environments/{self.team.pk}/observability/signal-snapshot/",
            {"dateRange": {"date_from": "2025-12-16T00:00:00Z", "date_to": "2025-12-17T00:00:00Z"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["logsTotal"] == 5
        assert data["logsWithJoinableTraceId"] == 2
        assert data["joinableTraceIdPercent"] == 40.0
        assert {r["service_name"] for r in data["logServiceNames"]} == {"svc-logs", "svc-both"}
        assert set(data["traceServiceNames"]) == {"svc-both", "svc-trace"}
        assert data["serviceNamesOverlap"] == ["svc-both"]
        assert set(data["logOnlyServiceNames"]) == {"svc-logs"}
        assert set(data["traceOnlyServiceNames"]) == {"svc-trace"}
        assert len(data["sampleJoinableTraceIds"]) == 2
        assert "resolvedDateRange" in data
