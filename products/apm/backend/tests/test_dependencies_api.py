import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

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
            # A retry wrapper is a client span whose child is the real client call, not a leaf dependency.
            retry = w.span(
                "web",
                name="retry GET api",
                kind=3,
                env="prod",
                trace=trace,
                parent=web,
                attributes={"server.address": "api.internal"},
            )
            # web's client span saw a timeout on trace 1 that the api server span never recorded.
            call = w.span(
                "web",
                name="GET api",
                kind=3,
                env="prod",
                trace=trace,
                parent=retry,
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
            w.span(
                "api",
                name="GET session",
                kind=3,
                env="prod",
                trace=trace,
                parent=api,
                attributes={"db.system.name": "redis", "server.address": "cache.internal"},
            )
            if trace == 1:
                # A database client that talks HTTP: the child names only the host, not the database.
                events = w.span(
                    "api",
                    name="SELECT events",
                    kind=3,
                    env="prod",
                    trace=trace,
                    parent=api,
                    attributes={"db.system": "clickhouse", "db.namespace": "events"},
                )
                w.span(
                    "api",
                    name="POST",
                    kind=3,
                    env="prod",
                    trace=trace,
                    parent=events,
                    attributes={"server.address": "ch.internal"},
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
        # A call that timed out before api recorded anything still counts on the web -> api edge.
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
        # A retry that names the service wraps an HTTP call that names only the load balancer and
        # reaches api. Both resolve to web -> api, so the request counts once.
        retried = w.span("web", name="GET /orders", env="prod", trace=6)
        named = w.span(
            "web", name="retry api", kind=3, env="prod", trace=6, parent=retried, attributes={"peer.service": "api"}
        )
        http = w.span(
            "web",
            name="GET",
            kind=3,
            env="prod",
            trace=6,
            parent=named,
            attributes={"server.address": "api-lb.internal"},
        )
        w.span("api", name="GET /orders", env="prod", trace=6, parent=http)
        # A database client without a namespace over HTTP to a host named like the database system.
        job = w.span("worker", name="run", env="prod", trace=7)
        query = w.span(
            "worker", name="SELECT", kind=3, env="prod", trace=7, parent=job, attributes={"db.system": "clickhouse"}
        )
        w.span(
            "worker",
            name="POST",
            kind=3,
            env="prod",
            trace=7,
            parent=query,
            attributes={"server.address": "clickhouse"},
        )
        root = w.span("eu-web", name="GET /", env="staging", trace=10)
        w.span("eu-web", name="query", kind=3, env="staging", trace=10, parent=root, attributes={"db.system": "redis"})
        w.insert()

    def _get(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", **params}
        query = {key: value for key, value in query.items() if value is not None}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_service_and_inferred_edges_with_caller_side_metrics(self) -> None:
        data = self._get()
        edges = {(e["caller"], e["callee"], e["kind"]): e for e in data["edges"]}
        self.assertEqual(
            {key: (e["inferred"], e["requests"], e["error_count"]) for key, e in edges.items()},
            {
                ("web", "api", "service"): (False, 6, 2),
                ("api", "web", "service"): (False, 4, 0),
                ("api", "postgresql:orders", "database"): (True, 4, 0),
                ("api", "redis", "database"): (True, 4, 0),
                ("api", "clickhouse:events", "database"): (True, 1, 0),
                ("api", "ch.internal", "external"): (True, 1, 0),
                ("api", "payments.example.com", "external"): (True, 2, 2),
                ("worker", "clickhouse", "database"): (True, 1, 0),
                ("worker", "clickhouse", "external"): (True, 1, 0),
            },
        )
        self.assertGreaterEqual(edges[("web", "api", "service")]["p95_ms"], 50)
        self.assertFalse(data["truncated"])
        self.assertEqual((data["sampled"], data["trace_count"]), (False, 7))

    def test_busy_window_reads_a_sample_of_whole_traces(self) -> None:
        with patch("products.apm.backend.logic.health.sources.MAP_TRACE_LIMIT", 3):
            data = self._get()
        self.assertEqual((data["sampled"], data["trace_count"]), (True, 3))
        full = {(e["caller"], e["callee"], e["kind"]): e["requests"] for e in self._get()["edges"]}
        sampled = {(e["caller"], e["callee"], e["kind"]): e["requests"] for e in data["edges"]}
        self.assertTrue(sampled)
        self.assertTrue(all(0 < requests <= full[key] for key, requests in sampled.items()), sampled)

    def test_service_filter_keeps_edges_on_either_side(self) -> None:
        data = self._get(service="web")
        self.assertEqual(
            {(e["caller"], e["callee"], e["requests"]) for e in data["edges"]}, {("web", "api", 6), ("api", "web", 4)}
        )
        self.assertEqual(data["service"], "web")
        self.assertEqual(
            {(e["caller"], e["callee"]) for e in self._get(service="api")["edges"]},
            {
                ("web", "api"),
                ("api", "web"),
                ("api", "postgresql:orders"),
                ("api", "redis"),
                ("api", "clickhouse:events"),
                ("api", "ch.internal"),
                ("api", "payments.example.com"),
            },
        )
        self.assertEqual(
            [(e["caller"], e["callee"], e["inferred"]) for e in self._get(service="payments.example.com")["edges"]],
            [("api", "payments.example.com", True)],
        )
        # No attribute holds the whole name of a database node, only its system and namespace apart.
        self.assertEqual(
            [(e["caller"], e["callee"], e["inferred"]) for e in self._get(service="postgresql:orders")["edges"]],
            [("api", "postgresql:orders", True)],
        )

    def test_session_request_is_refused_while_the_team_logs_api_slots_are_full(self) -> None:
        limiter = get_logs_api_team_rate_limiter()
        held_slots = [limiter.use(team_id=self.team.id) for _ in range(limiter.max_concurrency)]
        try:
            with patch.object(limiter, "retry_timeout", 0), patch(FLAG_PATCH, return_value=True):
                response = self.client.get(URL.format(self.team.id), {"date_from": DATE_FROM, "date_to": DATE_TO})
        finally:
            for slot in held_slots:
                if slot is not None:
                    limiter.release(slot)

        self.assertEqual(response.status_code, 429, response.content)
        self.assertEqual(limiter.redis_client.zcard(f"logs_api:query:per-team:{self.team.id}"), 0)

    def test_environment_filter(self) -> None:
        data = self._get(environment="staging")
        self.assertEqual(
            [(e["caller"], e["callee"], e["kind"]) for e in data["edges"]], [("eu-web", "redis", "database")]
        )

        everything = self._get(environment=None)
        self.assertIsNone(everything["environment"])
        callees = {(e["caller"], e["callee"]) for e in everything["edges"]}
        self.assertIn(("eu-web", "redis"), callees)
        self.assertTrue(callees > {("eu-web", "redis")})

    def test_edge_cap_keeps_service_edges_ahead_of_busier_inferred_ones(self) -> None:
        # api -> web has as many requests as api's database calls, which sort ahead of it by name.
        with patch("products.apm.backend.logic.health.dependencies.DEPENDENCY_EDGES_LIMIT", 2):
            data = self._get()
        self.assertEqual([(e["caller"], e["callee"]) for e in data["edges"]], [("web", "api"), ("api", "web")])
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
