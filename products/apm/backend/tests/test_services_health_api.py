import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestServicesHealthAPI(ClickhouseTestMixin, APIBaseTest):
    """One row per service from server spans, worst first, behind the product flag."""

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def _recreate_trace_spans_tables(cls) -> None:
        # is_root_span ships via a separate logs-cluster migration, not the Python DDL.
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()
        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        rows: list[str] = []
        n = 0

        def span(service: str, kind: int, status_code: int, ms: int, env: str = "", parent: str = "") -> None:
            nonlocal n
            n += 1
            start = base + dt.timedelta(seconds=n)
            attrs = f"map('deployment.environment.name', '{env}')" if env else "map()"
            rows.append(
                f"('019e8770-0000-0000-0000-{n:012d}', {cls.team.id}, '{_b64(n.to_bytes(16, 'big'))}', "
                f"'{_b64(n.to_bytes(8, 'big'))}', '{parent}', 'op', {kind}, "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', "
                f"'{(start + dt.timedelta(milliseconds=ms)).strftime('%Y-%m-%d %H:%M:%S.%f')}', "
                f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', {status_code}, '{service}', {attrs})"
            )

        # web: 10 server spans, 1 error -> 10%, serious. Client spans must not count as requests.
        for i in range(10):
            span("web", 2, 2 if i == 0 else 0, 50 + i, env="prod")
        span("web", 3, 2, 5, env="prod")
        # api: 20 server spans, no errors -> good
        for i in range(20):
            span("api", 2, 0, 20 + i, env="prod")
        # worker: no server spans; its root client spans carry the rate instead. 4 root spans, 1 error -> 25%
        for i in range(4):
            span("worker", 3, 2 if i == 0 else 0, 10, env="prod")
        # a service in another environment must not appear for prod
        for _ in range(3):
            span("eu-only", 2, 0, 30, env="staging")

        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES "
            + ",".join(rows)
        )

    def _list(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", **params}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/apm/services/", query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_one_row_per_service_worst_first(self) -> None:
        data = self._list()
        names = [r["service_name"] for r in data["results"]]
        self.assertEqual(names, ["worker", "web", "api"])
        web = data["results"][1]
        self.assertEqual(web["status"], "serious")
        self.assertEqual(web["health"]["span_count"], 10)
        self.assertEqual(web["health"]["error_count"], 1)
        self.assertAlmostEqual(web["health"]["error_rate"], 0.1)
        self.assertAlmostEqual(web["health"]["request_rate"], 10 / 7200, places=6)
        self.assertGreaterEqual(web["health"]["p95_ms"], 50)
        self.assertEqual(data["results"][2]["status"], "good")

    def test_root_client_spans_count_when_a_service_has_no_server_spans(self) -> None:
        worker = next(r for r in self._list()["results"] if r["service_name"] == "worker")
        self.assertEqual(worker["health"]["span_count"], 4)
        self.assertAlmostEqual(worker["health"]["error_rate"], 0.25)
        self.assertEqual(worker["status"], "serious")

    def test_environment_filters_and_is_listed(self) -> None:
        data = self._list()
        self.assertNotIn("eu-only", [r["service_name"] for r in data["results"]])
        self.assertEqual(sorted(data["environments"]), ["prod", "staging"])
        staging = self._list(environment="staging")
        self.assertEqual([r["service_name"] for r in staging["results"]], ["eu-only"])

    def test_each_row_carries_a_sparkline(self) -> None:
        for row in self._list()["results"]:
            self.assertEqual(len(row["sparkline"]), 24)
            self.assertEqual(sum(row["sparkline"]), row["health"]["span_count"])

    def test_defaults_to_the_last_hour_when_no_range_is_given(self) -> None:
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/apm/services/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [])

    def test_403_when_the_flag_is_off(self) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/apm/services/")
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_is_rejected(self) -> None:
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/apm/services/")
        self.assertEqual(response.status_code, 401)

    def test_other_team_sees_nothing(self) -> None:
        other = self.create_team_with_organization(organization=self.organization)
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(
                f"/api/projects/{other.id}/apm/services/",
                {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [])

    def test_queries_are_tagged_for_the_request_path(self) -> None:
        # The test base pre-tags the connection, so only an explicit check catches a request path that
        # forgets to tag and fails with UntaggedQueryError in a real server.
        with (
            patch(FLAG_PATCH, return_value=True),
            patch("products.apm.backend.presentation.views.tag_queries") as tag,
        ):
            self.client.get(f"/api/projects/{self.team.id}/apm/services/")
        tag.assert_called_once()
        self.assertTrue(tag.call_args.kwargs.get("product"))
        self.assertTrue(tag.call_args.kwargs.get("feature"))
