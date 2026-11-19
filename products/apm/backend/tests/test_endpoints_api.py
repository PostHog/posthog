import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from drf_spectacular.generators import SchemaGenerator

from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
URL = "/api/projects/{}/apm/endpoints/"


class TestEndpointsHealthAPI(ClickhouseTestMixin, APIBaseTest):
    """One row per (service, entry span name), worst first, behind the product flag."""

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def tearDownClass(cls):
        restore_trace_spans_tables()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        recreate_trace_spans_tables()
        w = SpanWriter(team_id=cls.team.id, base=dt.datetime(2026, 6, 2, 8, 0, 0))

        # web GET /orders: 10 server spans, 1 error -> 10%, serious.
        for i in range(10):
            root = w.span("web", name="GET /orders", status_code=2 if i == 0 else 0, ms=50 + i, env="prod")
        # A client span inside web is an outgoing call, not an endpoint.
        w.span("web", name="GET api/stock", kind=3, status_code=2, env="prod", parent=root)
        # web GET /health: 5 server spans, healthy.
        for _ in range(5):
            w.span("web", name="GET /health", env="prod")
        # web GET /report: satisfied, tolerating (between 500 ms and 2 s) and frustrated -> Apdex 0.5.
        for ms in (100, 900, 2500):
            w.span("web", name="GET /report", ms=ms, env="prod")
        # api POST /charge: a non-root server span is still an endpoint.
        for _ in range(4):
            w.span("api", name="POST /charge", env="prod", parent=root)
        # api internal span: kind 1 non-root is not an endpoint.
        w.span("api", name="db.query", kind=1, env="prod", parent=root)
        # queue consumer: kind 5 is an entry span.
        for i in range(2):
            w.span("queue", name="orders process", kind=5, status_code=2 if i == 0 else 0, env="prod", parent=root)
        # worker cron: a root client span is the entry of a job with no server spans.
        for _ in range(3):
            w.span("worker", name="cron.tick", kind=3, env="prod")
        # Another environment must not appear for prod.
        w.span("eu-only", name="GET /eu", env="staging")
        # Bare-method server spans keep the path template in an attribute, in their own environment.
        for _ in range(3):
            w.span("rest", name="POST", env="routes", attributes={"http.route": "/users/:id"})
        w.span("rest", name="POST", env="routes", attributes={"http.route": "/teams/:id"})
        w.span("rest", name="GET", env="routes", attributes={"url.template": "/items/{id}"})
        w.span("rest", name="GET", env="routes", attributes={"http.route": "/a/:id", "url.template": "/b/{id}"})
        w.span("rest", name="DELETE", env="routes")
        # A present but empty http.route still outranks url.template, as the drilldown's is_not_set guard reads it.
        w.span("rest", name="PUT", env="routes", attributes={"http.route": "", "url.template": "/x/{id}"})
        w.span("rest", name="process", env="routes", attributes={"http.route": "/ignored"})
        # Outgoing calls named only by their method take their target: the database system first, then the host.
        w.span("rest", name="GET", env="routes", attributes={"db.system": "redis", "net.peer.name": "cache.internal"})
        w.span(
            "rest", name="POST", env="routes", attributes={"server.address": "profiles.internal", "url.path": "/ingest"}
        )
        w.span("rest", name="HEAD", env="routes", attributes={"net.peer.name": "cache.internal"})
        w.insert()

    def _list(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", **params}
        query = {key: value for key, value in query.items() if value is not None}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_one_row_per_service_and_entry_span_worst_first(self) -> None:
        rows = [(r["service_name"], r["endpoint"]) for r in self._list()["results"]]
        self.assertEqual(
            rows,
            [
                ("queue", "orders process"),
                ("web", "GET /orders"),
                ("api", "POST /charge"),
                ("web", "GET /health"),
                ("web", "GET /report"),
                ("worker", "cron.tick"),
            ],
        )

    def test_row_carries_the_health_contract(self) -> None:
        orders = next(r for r in self._list()["results"] if r["endpoint"] == "GET /orders")
        self.assertEqual(orders["status"], "serious")
        self.assertEqual(orders["environment"], "prod")
        self.assertEqual(orders["health"]["span_count"], 10)
        self.assertEqual(orders["health"]["error_count"], 1)
        self.assertAlmostEqual(orders["health"]["error_rate"], 0.1)
        self.assertAlmostEqual(orders["health"]["request_rate"], 10 / 7200, places=6)
        self.assertGreaterEqual(orders["health"]["p95_ms"], 50)
        self.assertAlmostEqual(orders["health"]["apdex"], 0.9)
        report = next(r for r in self._list()["results"] if r["endpoint"] == "GET /report")
        self.assertAlmostEqual(report["health"]["apdex"], 0.5)

    def test_client_and_internal_child_spans_are_not_endpoints(self) -> None:
        endpoints = {r["endpoint"] for r in self._list()["results"]}
        self.assertNotIn("GET api/stock", endpoints)
        self.assertNotIn("db.query", endpoints)

    def test_service_filter(self) -> None:
        rows = self._list(service="web")["results"]
        self.assertEqual([r["endpoint"] for r in rows], ["GET /orders", "GET /health", "GET /report"])

    def test_environment_filter(self) -> None:
        self.assertNotIn("eu-only", {r["service_name"] for r in self._list()["results"]})
        staging = self._list(environment="staging")["results"]
        self.assertEqual([(r["service_name"], r["endpoint"]) for r in staging], [("eu-only", "GET /eu")])

    def test_no_environment_lists_endpoints_from_every_environment(self) -> None:
        everything = self._list(environment=None)
        self.assertIsNone(everything["environment"])
        per_environment = [
            row for env in ("prod", "staging", "routes") for row in self._list(environment=env)["results"]
        ]
        self.assertEqual(
            sorted((r["service_name"], r["endpoint"], r["health"]["span_count"]) for r in everything["results"]),
            sorted((r["service_name"], r["endpoint"], r["health"]["span_count"]) for r in per_environment),
        )

    def test_bare_method_spans_are_labelled_with_their_route(self) -> None:
        rows = {
            r["endpoint"]: (r["span_name"], r["route_attribute"], r["route"], r["health"]["span_count"])
            for r in self._list(environment="routes")["results"]
        }
        self.assertEqual(
            rows,
            {
                "POST /users/:id": ("POST", "http.route", "/users/:id", 3),
                "POST /teams/:id": ("POST", "http.route", "/teams/:id", 1),
                "GET /items/{id}": ("GET", "url.template", "/items/{id}", 1),
                "GET /a/:id": ("GET", "http.route", "/a/:id", 1),
                "DELETE": ("DELETE", None, None, 1),
                "PUT": ("PUT", None, None, 1),
                "process": ("process", None, None, 1),
                "GET redis": ("GET", "db.system", "redis", 1),
                "POST profiles.internal": ("POST", "server.address", "profiles.internal", 1),
                "HEAD cache.internal": ("HEAD", "net.peer.name", "cache.internal", 1),
            },
        )

    def test_rejects_a_window_over_seven_days(self) -> None:
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(
                URL.format(self.team.id), {"date_from": "2026-05-01T00:00:00Z", "date_to": "2026-06-02T00:00:00Z"}
            )
        self.assertEqual(response.status_code, 400)

    def test_403_when_the_flag_is_off(self) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = self.client.get(URL.format(self.team.id))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_is_rejected(self) -> None:
        self.client.logout()
        response = self.client.get(URL.format(self.team.id))
        self.assertEqual(response.status_code, 401)

    def test_other_team_sees_nothing(self) -> None:
        other = self.create_team_with_organization(organization=self.organization)
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(
                URL.format(other.id), {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [])

    def test_queries_are_tagged_for_the_request_path(self) -> None:
        with (
            patch(FLAG_PATCH, return_value=True),
            patch("products.apm.backend.presentation.views.tag_queries") as tag,
        ):
            self.client.get(URL.format(self.team.id))
        tag.assert_called_once()
        self.assertTrue(tag.call_args.kwargs.get("product"))
        self.assertTrue(tag.call_args.kwargs.get("feature"))


class TestEndpointsHealthOpenApiSchema(SimpleTestCase):
    def test_list_response_schema_is_a_single_object_not_an_array(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)
        operation = schema["paths"]["/api/projects/{project_id}/apm/endpoints/"]["get"]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertNotEqual(response_schema.get("type"), "array")
