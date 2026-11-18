import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from products.apm.backend.logic.health.deployments import compare_versions
from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
URL = "/api/projects/{}/apm/deployments/"


class TestDeploymentsAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def tearDownClass(cls):
        restore_trace_spans_tables()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        recreate_trace_spans_tables()
        w = SpanWriter(team_id=cls.team.id, base=dt.datetime(2026, 6, 2, 7, 10, 0), uuid_prefix="019e8775")
        for _ in range(10):
            w.span("api", env="prod", resource={"service.version": "1.0.0"}, ms=20)
        w.base = dt.datetime(2026, 6, 2, 8, 10, 0)
        w.n = 100
        for i in range(10):
            w.span("api", env="prod", resource={"service.version": "1.1.0"}, ms=60, status_code=2 if i < 3 else 0)
        w.span("api", env="prod", name="no version")
        w.span("worker", env="prod", resource={"service.version": "9.9.9"})
        w.insert()

    def _get(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", "service": "api", **params}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_versions_oldest_first_each_compared_with_the_previous(self) -> None:
        rows = self._get()["results"]
        self.assertEqual([r["version"] for r in rows], ["1.0.0", "1.1.0"])
        old, new = rows
        self.assertEqual(
            (old["requests"], old["error_count"], old["previous_version"], old["active"]), (10, 0, None, False)
        )
        self.assertEqual(
            (new["requests"], new["error_count"], new["previous_version"], new["active"]), (10, 3, "1.0.0", True)
        )
        self.assertAlmostEqual(new["error_rate_change"], 0.3)
        self.assertAlmostEqual(new["p95_change_pct"], 200, delta=15)
        self.assertLess(old["first_seen"], new["first_seen"])

    def test_service_is_required(self) -> None:
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), {"date_from": DATE_FROM, "date_to": DATE_TO})
        self.assertEqual(response.status_code, 400)


def test_compare_versions_leaves_changes_empty_without_a_previous_rate() -> None:
    t = dt.datetime(2026, 6, 2, 8)
    rows = [("1", t, t, 0, 0, 0, None), ("2", t, t, 5, 1, 5, 10.0)]
    versions = compare_versions(rows)
    assert versions[1].error_rate_change is None and versions[1].p95_change_pct is None
