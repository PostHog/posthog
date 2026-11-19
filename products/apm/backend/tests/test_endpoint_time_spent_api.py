import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from products.apm.backend.logic.time_spent import SpanRecord, attribute_time_spent
from products.apm.backend.tests.span_fixtures import SpanWriter, recreate_trace_spans_tables, restore_trace_spans_tables

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
FLAG_PATCH = "products.apm.backend.presentation.views.is_apm_enabled"
URL = "/api/projects/{}/apm/endpoint_time_spent/"


class TestEndpointTimeSpentAPI(ClickhouseTestMixin, APIBaseTest):
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

        # Each POST /orders request takes 100ms: 20ms in checkout itself, a 60ms call to payments of
        # which payments spends 50ms, and a 20ms query to an uninstrumented database.
        for trace in range(1, 3):
            t0 = dt.datetime(2026, 6, 2, 8, trace, 0)
            at = lambda ms, t0=t0: t0 + dt.timedelta(milliseconds=ms)  # noqa: E731
            entry = w.span("checkout", name="POST /orders", env="prod", trace=trace, start=at(0), ms=100)
            call = w.span(
                "checkout", name="POST pay", kind=3, env="prod", trace=trace, parent=entry, start=at(10), ms=60
            )
            w.span("payments", name="POST /pay", env="prod", trace=trace, parent=call, start=at(15), ms=50)
            w.span(
                "checkout",
                name="SELECT orders",
                kind=3,
                env="prod",
                trace=trace,
                parent=entry,
                start=at(75),
                ms=20,
                attributes={"db.system": "postgresql"},
            )
        # Another endpoint of the same service, and the same endpoint in staging, stay out of the breakdown.
        w.span("checkout", name="GET /health", env="prod", trace=10, ms=500)
        w.span("checkout", name="POST /orders", env="staging", trace=11, ms=900)
        # A bare-method span is found by its "<METHOD> <route>" label, not by the shared method name.
        w.span("checkout", name="GET", env="prod", trace=20, ms=40, attributes={"http.route": "/carts/:id"})
        w.span("checkout", name="GET", env="prod", trace=21, ms=80, attributes={"http.route": "/users/:id"})
        w.insert()

    def _get(self, **params) -> dict:
        query = {
            "date_from": DATE_FROM,
            "date_to": DATE_TO,
            "environment": "prod",
            "service": "checkout",
            "endpoint": "POST /orders",
            **params,
        }
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_splits_request_time_by_service_and_inferred_dependency(self) -> None:
        data = self._get()

        self.assertEqual(data["request_count"], 2)
        self.assertAlmostEqual(data["avg_duration_ms"], 100)
        self.assertEqual(
            [
                (c["name"], c["kind"], round(c["avg_ms_per_request"], 3), round(c["share"], 3))
                for c in data["components"]
            ],
            [
                ("payments", "service", 50, 0.5),
                ("checkout", "service", 30, 0.3),
                ("postgresql", "inferred", 20, 0.2),
            ],
        )

    def test_finds_a_bare_method_endpoint_by_its_route_label(self) -> None:
        data = self._get(endpoint="GET /carts/:id")

        self.assertEqual(data["request_count"], 1)
        self.assertAlmostEqual(data["avg_duration_ms"], 40)

    def test_requires_service_and_endpoint(self) -> None:
        with patch(FLAG_PATCH, return_value=True):
            response = self.client.get(URL.format(self.team.id), {"service": "checkout"})
        self.assertEqual(response.status_code, 400)


T0 = dt.datetime(2026, 6, 2, 8, 0, 0)


def _span(span_id: str, parent: str, service: str, start_ms: int, ms: int, kind: int = 1, inferred: str | None = None):
    return SpanRecord(
        trace_id="t",
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        kind=kind,
        timestamp=T0 + dt.timedelta(milliseconds=start_ms),
        end_time=T0 + dt.timedelta(milliseconds=start_ms + ms),
        duration_nano=ms * 1_000_000,
        inferred_dependency=inferred,
    )


class TestAttributeTimeSpent(SimpleTestCase):
    def test_leaf_client_span_without_peer_attributes_stays_with_its_service(self) -> None:
        spans = [_span("root", "", "web", 0, 100), _span("call", "root", "web", 0, 100, kind=3)]

        result = attribute_time_spent(spans, [("t", "root")])

        self.assertEqual([(c.name, c.share) for c in result.components], [("web", 1.0)])

    def test_folds_the_smallest_components_into_other(self) -> None:
        spans = [_span("root", "", "web", 0, 100)]
        spans += [_span(f"c{i}", "root", f"svc-{i}", i * 10, 10 - i % 2) for i in range(10)]

        with patch("products.apm.backend.logic.time_spent.TIME_SPENT_COMPONENT_LIMIT", 3):
            result = attribute_time_spent(spans, [("t", "root")])

        self.assertEqual([c.name for c in result.components], ["svc-0", "svc-2", "Other"])
        self.assertAlmostEqual(sum(c.share for c in result.components), 1.0)

    def test_a_span_that_names_itself_as_parent_is_counted_once(self) -> None:
        spans = [_span("root", "root", "web", 0, 100), _span("db", "root", "web", 0, 40, kind=3, inferred="pg")]

        result = attribute_time_spent(spans, [("t", "root")])

        self.assertEqual([(c.name, c.total_ms) for c in result.components], [("web", 60.0), ("pg", 40.0)])

    def test_nested_entries_and_work_after_the_response_are_not_counted_twice(self) -> None:
        spans = [
            _span("outer", "", "web", 0, 100),
            _span("inner", "outer", "web", 10, 50),
            _span("db", "inner", "web", 20, 20, kind=3, inferred="pg"),
            _span("job", "outer", "worker", 90, 1000),
        ]

        result = attribute_time_spent(spans, [("t", "inner"), ("t", "outer")])

        self.assertEqual(result.request_count, 1)
        self.assertEqual(
            [(c.name, c.total_ms) for c in result.components], [("web", 70.0), ("pg", 20.0), ("worker", 10.0)]
        )

    def test_parallel_calls_each_count_in_full_toward_the_shares(self) -> None:
        spans = [
            _span("root", "", "web", 0, 100),
            _span("a", "root", "payments", 10, 80),
            _span("b", "root", "inventory", 10, 80),
        ]

        result = attribute_time_spent(spans, [("t", "root")])

        self.assertEqual(
            [(c.name, c.total_ms, round(c.share, 3)) for c in result.components],
            [("inventory", 80.0, 0.444), ("payments", 80.0, 0.444), ("web", 20.0, 0.111)],
        )
