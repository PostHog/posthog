import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from drf_spectacular.generators import SchemaGenerator

from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
URL = "/api/projects/{}/apm/service_map/"


class TestServiceMapAPI(ClickhouseTestMixin, APIBaseTest):
    """Service-to-service edges from parent/child spans across services, over a bounded trace sample."""

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def tearDownClass(cls):
        restore_trace_spans_tables()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        recreate_trace_spans_tables()
        w = SpanWriter(team_id=cls.team.id, base=dt.datetime(2026, 6, 2, 8, 0, 0), uuid_prefix="019e8773")

        # Three traces web -> api -> db-svc. The api -> db-svc call fails in the first trace.
        for trace in range(1, 4):
            web = w.span("web", name="GET /orders", env="prod", trace=trace)
            call = w.span("web", name="GET api", kind=3, env="prod", trace=trace, parent=web)
            api = w.span("api", name="GET /orders", env="prod", trace=trace, parent=call, ms=40)
            # An internal child in the same service is not an edge.
            w.span("api", name="serialize", kind=1, env="prod", trace=trace, parent=api)
            w.span("db-svc", name="query", env="prod", trace=trace, parent=api, status_code=2 if trace == 1 else 0)
        # A trace in another environment must not add an edge to the prod map.
        root = w.span("eu-web", name="GET /", env="staging", trace=10)
        w.span("eu-api", name="GET /", env="staging", trace=10, parent=root)
        # A prod trace that calls into staging is sampled for prod, but its staging spans add no prod edges.
        prod_root = w.span("web", name="GET /sync", env="prod", trace=20)
        staging_child = w.span("eu-sync", name="POST /sync", env="staging", trace=20, parent=prod_root)
        w.span("eu-store", name="write", env="staging", trace=20, parent=staging_child)
        w.insert()

    def _get(self, **params) -> dict:
        query = {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod", **params}
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_edges_cross_services_only_with_call_and_error_counts(self) -> None:
        data = self._get()
        edges = {(e["caller"], e["callee"]): e for e in data["edges"]}
        self.assertEqual(set(edges), {("web", "api"), ("api", "db-svc")})
        self.assertEqual(edges[("web", "api")]["calls"], 3)
        self.assertEqual(edges[("web", "api")]["error_count"], 0)
        self.assertEqual(edges[("api", "db-svc")]["calls"], 3)
        self.assertEqual(edges[("api", "db-svc")]["error_count"], 1)
        self.assertGreaterEqual(edges[("web", "api")]["p95_ms"], 40)
        self.assertEqual(data["trace_count"], 4)

    def test_environment_filter(self) -> None:
        data = self._get(environment="staging")
        # The cross-environment trace adds its staging-only edge here, and not the prod -> staging call.
        self.assertEqual(
            sorted((e["caller"], e["callee"]) for e in data["edges"]), [("eu-sync", "eu-store"), ("eu-web", "eu-api")]
        )
        self.assertEqual(data["trace_count"], 2)

    def test_trace_sample_is_capped(self) -> None:
        with patch("products.apm.backend.logic.health.sources.MAP_TRACE_LIMIT", 1):
            data = self._get()
        self.assertEqual(data["trace_count"], 1)
        self.assertEqual({e["calls"] for e in data["edges"]}, {1})

    def test_span_input_to_the_join_is_capped(self) -> None:
        # One span has no parent to join to, so a one-span budget leaves no edges over the same trace sample.
        with patch("products.apm.backend.logic.health.sources.MAP_SPAN_LIMIT", 1):
            data = self._get()
        self.assertEqual(data["edges"], [])
        self.assertEqual(data["trace_count"], 4)

    def test_403_when_the_flag_is_off(self) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = self.client.get(URL.format(self.team.id))
        self.assertEqual(response.status_code, 403)

    def test_other_team_sees_nothing(self) -> None:
        other = self.create_team_with_organization(organization=self.organization)
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(
                URL.format(other.id), {"date_from": DATE_FROM, "date_to": DATE_TO, "environment": "prod"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["edges"], [])

    def test_queries_are_tagged_for_the_request_path(self) -> None:
        with (
            patch(FLAG_PATCH, return_value=True),
            patch("products.apm.backend.presentation.views.tag_queries") as tag,
        ):
            self.client.get(URL.format(self.team.id))
        tag.assert_called_once()


class TestServiceMapOpenApiSchema(SimpleTestCase):
    def test_list_response_schema_is_a_single_object_not_an_array(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)
        operation = schema["paths"]["/api/projects/{project_id}/apm/service_map/"]["get"]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertNotEqual(response_schema.get("type"), "array")
