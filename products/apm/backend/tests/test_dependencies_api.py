import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_USER_MESSAGE
from posthog.clickhouse.client.limit import get_logs_api_team_rate_limiter
from posthog.errors import CHQueryErrorTooManyBytes

from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
URL = "/api/projects/{}/apm/dependencies/"


class TestDependenciesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def tearDownClass(cls):
        restore_trace_spans_tables()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        recreate_trace_spans_tables()
        w = SpanWriter(team_id=cls.team.id, base=dt.datetime(2026, 6, 2, 8, 0, 0), uuid_prefix="019e8774")

        for trace in range(1, 5):
            web = w.span("web", name="GET /orders", env="prod", trace=trace)
            # web's client span saw a timeout on trace 1 that the api server span never recorded.
            call = w.span(
                "web",
                name="GET api",
                kind=3,
                env="prod",
                trace=trace,
                parent=web,
                ms=50,
                status_code=2 if trace == 1 else 0,
            )
            api = w.span("api", name="GET /orders", env="prod", trace=trace, parent=call, ms=40)
            w.span("api", name="serialize", kind=1, env="prod", trace=trace, parent=api)
            w.span(
                "api",
                name="SELECT orders",
                kind=3,
                env="prod",
                trace=trace,
                parent=api,
                attributes={"db.system": "postgresql", "db.name": "orders"},
            )
            if trace <= 2:
                w.span(
                    "api",
                    name="POST",
                    kind=3,
                    env="prod",
                    trace=trace,
                    parent=api,
                    status_code=2,
                    attributes={"server.address": "payments.example.com", "http.request.method": "POST"},
                )
            w.span(
                "api", name="GET web", kind=3, env="prod", trace=trace, parent=api, attributes={"peer.service": "web"}
            )
        # web's call on trace 5 timed out before api recorded anything, so it has no child span.
        lost = w.span("web", name="GET /orders", env="prod", trace=5)
        w.span(
            "web",
            name="GET api",
            kind=3,
            env="prod",
            trace=5,
            parent=lost,
            status_code=2,
            attributes={"peer.service": "api"},
        )
        root = w.span("eu-web", name="GET /", env="staging", trace=10)
        w.span("eu-web", name="query", kind=3, env="staging", trace=10, parent=root, attributes={"db.system": "redis"})
        w.span(
            "eu-web",
            name="SELECT",
            kind=3,
            env="staging",
            trace=10,
            parent=root,
            attributes={"db.system.name": "postgresql", "db.namespace": "shop", "server.address": "db.example.com"},
        )
        w.insert()

    def _get(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", **params}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_service_and_inferred_edges_with_caller_side_metrics(self) -> None:
        data = self._get()
        edges = {(e["caller"], e["callee"]): e for e in data["edges"]}
        self.assertEqual(
            {key: (e["inferred"], e["kind"], e["requests"], e["error_count"]) for key, e in edges.items()},
            {
                ("web", "api"): (False, "service", 5, 2),
                ("api", "postgresql:orders"): (True, "database", 4, 0),
                ("api", "payments.example.com"): (True, "external", 2, 2),
            },
        )
        self.assertGreaterEqual(edges[("web", "api")]["p95_ms"], 50)
        self.assertFalse(data["truncated"])

    @parameterized.expand(
        [
            ("caller", "web", [("web", "api", 5)]),
            ("callee", "api", [("web", "api", 5), ("api", "postgresql:orders", 4), ("api", "payments.example.com", 2)]),
        ]
    )
    def test_service_filter_keeps_edges_on_either_side(self, _name: str, service: str, expected: list) -> None:
        data = self._get(service=service)
        self.assertEqual([(e["caller"], e["callee"], e["requests"]) for e in data["edges"]], expected)
        self.assertEqual(data["service"], service)

    def test_environment_filter(self) -> None:
        data = self._get(environment="staging")
        self.assertEqual(
            sorted((e["caller"], e["callee"], e["kind"]) for e in data["edges"]),
            [("eu-web", "postgresql:shop", "database"), ("eu-web", "redis", "database")],
        )

    def test_edge_cap_sets_truncated(self) -> None:
        with patch("products.apm.backend.logic.health.dependencies.DEPENDENCY_EDGES_LIMIT", 1):
            data = self._get()
        self.assertEqual(len(data["edges"]), 1)
        self.assertTrue(data["truncated"])

    def test_too_many_bytes_is_a_validation_error(self) -> None:
        with (
            patch(FLAG_PATCH, return_value=True),
            patch(
                "products.apm.backend.presentation.views.get_dependencies",
                side_effect=CHQueryErrorTooManyBytes("too many bytes"),
            ),
        ):
            response = self.client.get(URL.format(self.team.id), {"date_from": DATE_FROM, "date_to": DATE_TO})
        self.assertEqual(response.status_code, 400)

    def test_api_key_is_refused_while_the_team_logs_api_slots_are_full(self) -> None:
        key = self.create_personal_api_key_with_scopes(["tracing:read"])
        limiter = get_logs_api_team_rate_limiter()
        held_slots = [limiter.use(team_id=self.team.id) for _ in range(limiter.max_concurrency)]
        try:
            with patch.object(limiter, "retry_timeout", 0), patch(FLAG_PATCH, return_value=True):
                self.client.logout()
                response = self.client.get(
                    URL.format(self.team.id),
                    {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod"},
                    HTTP_AUTHORIZATION=f"Bearer {key}",
                )
        finally:
            for slot in held_slots:
                if slot is not None:
                    limiter.release(slot)
        self.assertEqual(response.status_code, 429, response.content)
        self.assertTrue(response.json()["detail"].startswith(CONCURRENCY_LIMIT_USER_MESSAGE))
