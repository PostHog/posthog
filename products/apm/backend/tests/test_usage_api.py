import json
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute

from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-10-02T07:00:00Z"
DATE_TO = "2026-10-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
INSIDE = dt.datetime(2026, 10, 2, 8, 0, 0)
OUTSIDE = dt.datetime(2026, 10, 2, 10, 30, 0)
FAR_FUTURE = "2200-01-01 00:00:00.000000"


def _ts(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def insert_logs(team_id: int, service: str, sizes: list[int], at: dt.datetime = INSIDE) -> None:
    rows = [
        {
            "team_id": team_id,
            "timestamp": _ts(at + dt.timedelta(seconds=i)),
            "observed_timestamp": _ts(at + dt.timedelta(seconds=i)),
            "original_expiry_timestamp": FAR_FUTURE,
            "service_name": service,
            "severity_text": "info",
            "body": "x" * 5,
            "_bytes_uncompressed": size,
        }
        for i, size in enumerate(sizes)
    ]
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in rows))


def insert_metric_points(team_id: int, service: str, series: int, points: int, at: dt.datetime = INSIDE) -> None:
    rows = [
        {
            "team_id": team_id,
            "metric_name": f"{service}.requests",
            "series_fingerprint": hash((team_id, service, s)) & 0x7FFFFFFFFFFFFFFF,
            "timestamp": _ts(at + dt.timedelta(seconds=p)),
            "observed_timestamp": _ts(at + dt.timedelta(seconds=p)),
            "original_expiry_timestamp": FAR_FUTURE,
            "service_name": service,
            "metric_type": "gauge",
            "value": float(p),
            "count": 1,
            "has_labels": True,
            "attributes": {"series": str(s)},
            "resource_attributes": {},
        }
        for s in range(series)
        for p in range(points)
    ]
    sync_execute("INSERT INTO metrics4_input FORMAT JSONEachRow " + "\n".join(json.dumps(row) for row in rows))


class TestServiceUsageAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def tearDownClass(cls):
        restore_trace_spans_tables()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        recreate_trace_spans_tables()
        for table in ("logs34", "metrics4_samples", "metrics4_series", "metrics4_names", "metrics4_attributes"):
            sync_execute(f"TRUNCATE TABLE IF EXISTS {table}")
        other_team_id = cls.team.id + 1000

        # checkout sends all three signals and must collapse into one row.
        insert_logs(cls.team.id, "checkout", [100, 200, 300])
        spans = SpanWriter(team_id=cls.team.id, base=INSIDE)
        for _ in range(4):
            spans.span("checkout")
        # Spans count every kind, not only requests: usage is about what is stored.
        spans.span("checkout", kind=3)
        for _ in range(7):
            spans.span("api")
        spans.insert()
        insert_metric_points(cls.team.id, "checkout", series=2, points=3)
        # proxy sends only logs, and the most bytes, so it sorts first.
        insert_logs(cls.team.id, "proxy", [5000, 5000])
        # node-exporter sends only metrics.
        insert_metric_points(cls.team.id, "node-exporter", series=3, points=4)

        # Rows outside the window or for another team must not count.
        insert_logs(cls.team.id, "proxy", [99999], at=OUTSIDE)
        insert_metric_points(cls.team.id, "node-exporter", series=1, points=5, at=OUTSIDE)
        insert_logs(other_team_id, "proxy", [77777])
        other_spans = SpanWriter(team_id=other_team_id, base=INSIDE, uuid_prefix="019e8773")
        other_spans.span("api")
        other_spans.insert()

    def _get(self, flag: bool = True, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, **params}
        with patch(FLAG_PATCH, return_value=flag):
            response = self.client.get(f"/api/projects/{self.team.id}/apm/usage/", query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_one_row_per_service_across_all_signals(self) -> None:
        data = self._get()

        rows = {row["service_name"]: row for row in data["results"]}
        self.assertEqual(
            [row["service_name"] for row in data["results"]], ["proxy", "checkout", "api", "node-exporter"]
        )
        self.assertEqual(
            rows["checkout"],
            {
                "service_name": "checkout",
                "log_records": 3,
                "log_bytes": 600,
                "spans": 5,
                "metric_points": 6,
                "metric_series": 2,
            },
        )
        self.assertEqual(rows["proxy"]["log_bytes"], 10000)
        self.assertEqual(rows["proxy"]["spans"], 0)
        self.assertEqual(rows["api"]["spans"], 7)
        self.assertEqual((rows["node-exporter"]["metric_points"], rows["node-exporter"]["metric_series"]), (12, 3))
        self.assertEqual(
            data["totals"],
            {"log_records": 5, "log_bytes": 10600, "spans": 12, "metric_points": 18, "metric_series": 5},
        )
        self.assertEqual(data["unavailable_signals"], [])

    def test_empty_window_returns_no_rows(self) -> None:
        data = self._get(date_from="2026-10-01T00:00:00Z", date_to="2026-10-01T01:00:00Z")

        self.assertEqual(data["results"], [])
        self.assertEqual(
            data["totals"], {"log_records": 0, "log_bytes": 0, "spans": 0, "metric_points": 0, "metric_series": 0}
        )

    def test_a_failing_signal_is_reported_and_the_others_still_load(self) -> None:
        with patch("products.apm.backend.logic.usage.LOGS_USAGE_QUERY", "SELECT throwIf(1, 'timeout') FROM logs"):
            data = self._get()

        self.assertEqual(data["unavailable_signals"], ["logs"])
        rows = {row["service_name"]: row for row in data["results"]}
        self.assertNotIn("proxy", rows)
        self.assertEqual(rows["api"]["spans"], 7)
        self.assertEqual(data["totals"]["log_bytes"], 0)

    def test_403_when_the_flag_is_off(self) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/apm/usage/", {"date_from": DATE_FROM})
        self.assertEqual(response.status_code, 403)

    def test_400_when_the_window_is_longer_than_seven_days(self) -> None:
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/apm/usage/",
                {"date_from": "2026-09-20T00:00:00Z", "date_to": DATE_TO},
            )
        self.assertEqual(response.status_code, 400)
