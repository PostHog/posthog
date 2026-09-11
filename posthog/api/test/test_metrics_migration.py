import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.metrics_migration_report import (
    ROLLUP_SUFFIXES,
    build_report,
    is_covered,
    load_grafana_metrics,
    merge_live_ingested,
    normalize_name,
)


class TestNormalizeName(APIBaseTest):
    def test_rollup_suffixes_collapse_to_base(self):
        for suffix in ROLLUP_SUFFIXES:
            self.assertEqual(normalize_name(f"http_seconds{suffix}"), "http_seconds")

    def test_plain_name_unchanged(self):
        self.assertEqual(normalize_name("node_load1"), "node_load1")


class TestIsCovered(APIBaseTest):
    def test_exact_match(self):
        self.assertTrue(is_covered("up", {"up"}))

    def test_histogram_bucket_matches_ingested_base_name(self):
        self.assertTrue(is_covered("capture_v1_response_time_seconds_bucket", {"capture_v1_response_time_seconds"}))

    def test_missing(self):
        self.assertFalse(is_covered("flags_decide_latency_seconds", {"up"}))


class TestBuildReport(APIBaseTest):
    def test_counts_and_status(self):
        grafana = {"up": ["dash a"], "missing_one": ["dash a", "dash b"], "missing_two": ["dash b"]}
        dashboards = {
            "dash a": {"up", "missing_one"},
            "dash b": {"missing_one", "missing_two"},
            "dash c": {"up"},
        }
        report = build_report(grafana_metrics=grafana, dashboard_metrics=dashboards, ingested={"up"})

        self.assertEqual(report["summary"]["grafana_metric_names"], 3)
        self.assertEqual(report["summary"]["covered"], 1)
        self.assertEqual(report["summary"]["uncovered"], 2)
        self.assertAlmostEqual(report["summary"]["coverage_pct"], 100 / 3, places=1)
        self.assertEqual(report["summary"]["dashboards_total"], 3)
        self.assertEqual(report["summary"]["dashboards_fully_covered"], 1)

        by_title = {d["title"]: d for d in report["dashboards"]}
        self.assertEqual(by_title["dash c"]["status"], "covered")
        self.assertEqual(by_title["dash a"]["status"], "partial")
        self.assertEqual(by_title["dash b"]["status"], "missing")
        self.assertEqual(by_title["dash a"]["covered_metrics"], 1)
        self.assertEqual(by_title["dash a"]["uncovered_metrics"], 1)

    def test_uncovered_lists_referencing_dashboards(self):
        report = build_report(
            grafana_metrics={"gone": ["dash a"]},
            dashboard_metrics={"dash a": {"gone"}},
            ingested=set(),
        )
        self.assertEqual(report["uncovered"], [{"name": "gone", "dashboards": ["dash a"]}])

    def test_empty_grafana_inventory_yields_zero_percent(self):
        report = build_report(grafana_metrics={}, dashboard_metrics={}, ingested={"up"})
        self.assertEqual(report["summary"]["coverage_pct"], 0.0)


class TestLoadGrafanaMetrics(APIBaseTest):
    def test_parses_committed_snapshot(self):
        payload = {
            "summary": {"coverage_pct": 50.0, "covered": 1, "grafana_metric_names": 2},
            "dashboards": [
                {
                    "title": "dash a",
                    "covered_metrics": 1,
                    "uncovered_metrics": 1,
                    "coverage_pct": 50.0,
                    "status": "partial",
                    "metric_count": 2,
                    "file": "a.json",
                }
            ],
            "uncovered": [{"name": "missing_one", "dashboards": ["dash a"]}],
        }
        grafana_metrics, dashboard_metrics = load_grafana_metrics(payload)
        self.assertEqual(grafana_metrics["missing_one"], ["dash a"])
        self.assertEqual(dashboard_metrics["dash a"], {"missing_one"})


class TestMergeLiveIngested(APIBaseTest):
    SNAPSHOT = {
        "summary": {
            "grafana_metric_names": 2,
            "covered": 1,
            "uncovered": 1,
            "coverage_pct": 50.0,
            "posthog_ingested_names": 1,
        },
        "dashboards": [],
        "uncovered": [{"name": "missing_one", "dashboards": ["dash a"]}],
    }

    def test_newly_ingested_metric_moves_to_covered(self):
        merged = merge_live_ingested(self.SNAPSHOT, {"up", "missing_one"})
        self.assertEqual(merged["summary"]["coverage_pct"], 100.0)
        self.assertEqual(merged["summary"]["covered"], 2)
        self.assertEqual(merged["summary"]["posthog_ingested_names"], 2)
        self.assertEqual(merged["uncovered"], [])
        self.assertTrue(merged["live"])

    def test_no_new_ingestion_keeps_snapshot(self):
        merged = merge_live_ingested(self.SNAPSHOT, {"up"})
        self.assertEqual(merged["summary"]["coverage_pct"], 50.0)
        self.assertEqual(len(merged["uncovered"]), 1)


class TestMetricsMigrationEndpoint(APIBaseTest):
    SNAPSHOT = {
        "generated_at": "2026-09-11T00:00:00+00:00",
        "summary": {
            "grafana_metric_names": 2,
            "posthog_ingested_names": 1,
            "covered": 1,
            "uncovered": 1,
            "coverage_pct": 50.0,
            "dashboards_total": 1,
            "dashboards_fully_covered": 0,
        },
        "dashboards": [
            {
                "title": "dash a",
                "file": "a.json",
                "metric_count": 2,
                "covered_metrics": 1,
                "uncovered_metrics": 1,
                "coverage_pct": 50.0,
                "status": "partial",
            }
        ],
        "uncovered": [{"name": "missing_one", "dashboards": ["dash a"]}],
    }

    @parameterized.expand([("non_staff", False, status.HTTP_403_FORBIDDEN), ("staff", True, status.HTTP_200_OK)])
    @patch("posthog.metrics_migration_report.load_snapshot", autospec=True)
    def test_requires_staff(self, _name, is_staff, expected_status, mock_load):
        mock_load.return_value = self.SNAPSHOT
        self.user.is_staff = is_staff
        self.user.save()

        response = self.client.get("/api/instance_status/metrics_migration")

        self.assertEqual(response.status_code, expected_status, response.content)
        if expected_status == status.HTTP_200_OK:
            body = response.json()["results"]
            self.assertEqual(body["summary"]["coverage_pct"], 50.0)
            self.assertEqual(body["dashboards"][0]["title"], "dash a")

    @patch("posthog.metrics_migration_report.load_snapshot", return_value=None)
    def test_missing_snapshot_returns_404(self, _mock):
        self.user.is_staff = True
        self.user.save()

        response = self.client.get("/api/instance_status/metrics_migration")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @pytest.mark.skip_on_multitenancy
    @patch("posthog.metrics_migration_report.load_snapshot")
    def test_live_counts_merge(self, mock_load):
        self.user.is_staff = True
        self.user.save()
        mock_load.return_value = self.SNAPSHOT

        with patch(
            "posthog.metrics_migration_report.ingested_metric_names",
            return_value={"up", "missing_one"},
        ):
            response = self.client.get("/api/instance_status/metrics_migration?live=true")

        body = response.json()["results"]
        self.assertEqual(body["summary"]["posthog_ingested_names"], 2)
        # missing_one is now ingested, so coverage recomputes to 100%
        self.assertEqual(body["summary"]["coverage_pct"], 100.0)
        self.assertEqual(body["uncovered"], [])
        self.assertTrue(body["live"])
