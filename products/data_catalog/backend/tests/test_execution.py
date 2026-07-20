import json
from typing import cast
from urllib.parse import parse_qs, unquote, urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.query_runner import ExecutionMode

from products.data_catalog.backend.logic.execution import prepare_execution_query, run_metric
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.models import Metric

_HOGQL = {"kind": "HogQLQuery", "query": "select count() as c from events"}
_EVENTS_NODE = {"kind": "EventsNode", "event": "purchase"}
_PROCESS_QUERY = "products.data_catalog.backend.logic.execution.process_query_dict"
_OK_PAYLOAD = {"results": [[1]], "hogql": "SELECT 1"}


def _decoded_insight_link(url: str) -> dict:
    fragment = urlparse(url).fragment
    assert fragment.startswith("q="), url
    return json.loads(unquote(fragment[2:]))


def _decoded_sql_editor_link(url: str) -> dict:
    return json.loads(parse_qs(urlparse(url).query)["open_query"][0])


class TestMetricRunExecution(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.run_url = f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/run/"
        for i in range(3):
            _create_event(team=self.team, event="purchase", distinct_id=f"user_{i}")
        flush_persons_and_events()

    def test_run_envelope_matches_direct_execution(self) -> None:
        # The RFC's same-engine guarantee: metric-run must return exactly what running the definition
        # directly returns, wrapped in the envelope.
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        response = self.client.post(self.run_url)
        assert response.status_code == status.HTTP_200_OK, response.json()

        body = response.json()
        assert set(body) >= {"status", "is_drifted", "unit", "kind", "results", "compiled_query", "query_status"}
        assert body["kind"] == "HogQLQuery"
        assert body["is_drifted"] is False
        assert "/sql?open_query=" in body["posthog_url"]

        assert metric.definition is not None
        direct = process_query_dict(
            self.team, metric.definition, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )
        direct_json = direct.model_dump(mode="json") if hasattr(direct, "model_dump") else direct
        assert body["results"] == direct_json["results"]
        assert body["results"] == [[3]]

    def test_run_events_node_executes_as_trends(self) -> None:
        # A bare EventsNode has no query runner; the run must still return the number by executing
        # it as a single-series trends query, while the envelope keeps the stored kind.
        upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_EVENTS_NODE)
        response = self.client.post(self.run_url)
        assert response.status_code == status.HTTP_200_OK, response.json()

        body = response.json()
        assert body["kind"] == "EventsNode"
        assert body["results"][0]["count"] == 3


class TestMetricRunPreparation(APIBaseTest):
    def _run(self, definition: dict, **overrides: str) -> tuple[dict, dict]:
        """Run a metric with the engine mocked; returns (query handed to the engine, envelope)."""
        metric = upsert_metric(team=self.team, user=self.user, name="prep", description="d", definition=definition)
        captured: dict = {}

        def capture(team: object, query: dict, **kwargs: object) -> dict:
            captured.update(query)
            return dict(_OK_PAYLOAD)

        with patch(_PROCESS_QUERY, side_effect=capture):
            envelope = run_metric(team=self.team, metric=metric, user=self.user, **overrides)
        return captured, envelope

    @parameterized.expand(
        [
            ("events", {"kind": "EventsNode", "event": "purchase"}),
            ("actions", {"kind": "ActionsNode", "id": 1}),
            (
                "data_warehouse",
                {
                    "kind": "DataWarehouseNode",
                    "id": "orders",
                    "table_name": "orders",
                    "id_field": "id",
                    "distinct_id_field": "user_id",
                    "timestamp_field": "created_at",
                },
            ),
        ]
    )
    def test_node_definitions_execute_as_single_series_trends(self, _name: str, node: dict) -> None:
        executed, envelope = self._run(node)
        assert executed["kind"] == "TrendsQuery"
        assert executed["series"] == [node]
        assert envelope["kind"] == node["kind"]

    def test_date_overrides_reach_executed_query_and_deep_link(self) -> None:
        definition = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "purchase"}]}
        executed, envelope = self._run(definition, date_from="-30d", date_to="-1d", interval="week")
        assert executed["dateRange"] == {"date_from": "-30d", "date_to": "-1d"}
        assert executed["interval"] == "week"

        linked = _decoded_insight_link(envelope["posthog_url"])
        assert linked["kind"] == "InsightVizNode"
        assert linked["source"] == executed

    def test_hogql_values_round_trip_through_deep_link(self) -> None:
        definition = {"kind": "HogQLQuery", "query": "select count() from events", "values": {"threshold": 10}}
        _, envelope = self._run(definition)
        linked = _decoded_sql_editor_link(envelope["posthog_url"])
        assert linked["kind"] == "DataVisualizationNode"
        assert linked["source"] == definition

    def test_error_payload_is_a_failed_run(self) -> None:
        # The engine reports schema-validation failures as {"error": ...} without raising; that must
        # surface as a 400, not a successful run with null results.
        metric = upsert_metric(team=self.team, user=self.user, name="prep", description="d", definition=_HOGQL)
        with patch(_PROCESS_QUERY, return_value={"results": None, "error": "1 validation error"}):
            with self.assertRaises(ValidationError):
                run_metric(team=self.team, metric=metric, user=self.user)
        metric.refresh_from_db()
        assert metric.last_run_at is None

    @parameterized.expand(
        [
            ("exposed_hogql", ExposedHogQLError("no such table"), ValidationError),
            ("exposed_clickhouse", ExposedCHQueryError("memory limit"), ValidationError),
            ("concurrency", ConcurrencyLimitExceeded("too many"), Throttled),
            ("unexpected", RuntimeError("engine bug"), RuntimeError),
        ]
    )
    def test_engine_exceptions_keep_their_http_semantics(
        self, _name: str, engine_error: Exception, expected: type[Exception]
    ) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="prep", description="d", definition=_HOGQL)
        with patch(_PROCESS_QUERY, side_effect=engine_error):
            with self.assertRaises(expected):
                run_metric(team=self.team, metric=metric, user=self.user)
        metric.refresh_from_db()
        assert metric.last_run_at is None

    @parameterized.expand(
        [
            ("date_from", {"date_from": "-7d"}, "date_from"),
            ("date_to", {"date_to": "-1d"}, "date_to"),
            ("interval", {"interval": "week"}, "interval"),
        ]
    )
    def test_hogql_date_override_names_the_provided_field(self, _name: str, params: dict, expected_field: str) -> None:
        # The rejection must point at whichever date param the caller actually sent, not always date_from.
        with self.assertRaises(ValidationError) as ctx:
            prepare_execution_query(_HOGQL, **params)
        detail = cast(dict, ctx.exception.detail)
        assert str(detail["field"]) == expected_field


class TestMetricRunAttribution(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The markdown path exercises the same attribution code without a ClickHouse query.
        upsert_metric(
            team=self.team,
            user=self.user,
            name="activation",
            description="d",
            definition={"kind": "MarkdownDefinition", "markdown": "1. Count activated users."},
        )
        self.run_url = f"/api/projects/{self.team.id}/data_catalog/metrics/activation/run/"

    def test_last_run_at_set_and_throttled(self) -> None:
        self.client.post(self.run_url)
        metric = Metric.objects.for_team(self.team.id).get(name="activation")
        first_run = metric.last_run_at
        assert first_run is not None

        self.client.post(self.run_url)
        metric.refresh_from_db()
        assert metric.last_run_at == first_run  # within the 30-minute throttle window


class TestMetricRunTagging(APIBaseTest):
    def test_run_tags_clickhouse_query_with_data_catalog_product(self) -> None:
        # run_metric executes queries via process_query_dict directly, so it must set the query tags
        # itself. Untagged, ClickHouse queries warn in prod and hard-fail in local dev; TEST disables
        # tag enforcement, so only this explicit assertion guards against dropping the tags.
        metric = upsert_metric(team=self.team, user=self.user, name="tagged", description="d", definition=_HOGQL)
        captured: dict[str, object] = {}

        def capture(*args: object, **kwargs: object) -> dict:
            tags = get_query_tags()
            captured["product"], captured["feature"] = tags.product, tags.feature
            return dict(_OK_PAYLOAD)

        with patch(_PROCESS_QUERY, side_effect=capture):
            run_metric(team=self.team, metric=metric, user=self.user)

        assert (captured["product"], captured["feature"]) == (Product.DATA_CATALOG, Feature.QUERY)

    @parameterized.expand(
        [
            ("personal_api_key", "personal_api_key", True),
            ("project_secret_api_key", "project_secret_api_key", True),
            ("oauth", "oauth", False),
            ("no_access_method", None, False),
        ]
    )
    def test_run_propagates_is_query_service_from_access_method(
        self, _name: str, access_method: str | None, expected: bool
    ) -> None:
        # API-key runs must hit /query's safeguards (rejected constructs, API-team concurrency limit);
        # dropping the propagation lets a stored query bypass them, so lock the mapping in.
        metric = upsert_metric(team=self.team, user=self.user, name="svc", description="d", definition=_HOGQL)
        captured: dict[str, object] = {}

        def capture(*args: object, **kwargs: object) -> dict:
            captured["is_query_service"] = kwargs.get("is_query_service")
            return dict(_OK_PAYLOAD)

        with patch(_PROCESS_QUERY, side_effect=capture), tags_context(access_method=access_method):
            run_metric(team=self.team, metric=metric, user=self.user)

        assert captured["is_query_service"] is expected
