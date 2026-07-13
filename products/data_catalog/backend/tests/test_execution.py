from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from rest_framework import status

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.hogql_queries.query_runner import ExecutionMode

from products.data_catalog.backend.logic.execution import run_metric
from products.data_catalog.backend.logic.metrics import upsert_metric

_HOGQL = {"kind": "HogQLQuery", "query": "select count() as c from events"}


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
        assert set(body) >= {"status", "unit", "kind", "results", "compiled_query", "query_status", "posthog_url"}
        assert body["kind"] == "HogQLQuery"
        assert "/sql?open_query=" in body["posthog_url"]

        assert metric.definition is not None
        direct = process_query_dict(
            self.team, metric.definition, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )
        direct_json = direct.model_dump(mode="json") if hasattr(direct, "model_dump") else direct
        assert body["results"] == direct_json["results"]
        assert body["results"] == [[3]]

    def test_last_run_at_set_and_throttled(self) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        self.client.post(self.run_url)
        metric.refresh_from_db()
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
            return {"results": [[1]], "hogql": "SELECT 1"}

        with patch("products.data_catalog.backend.logic.execution.process_query_dict", side_effect=capture):
            run_metric(team=self.team, metric=metric, user=self.user)

        assert (captured["product"], captured["feature"]) == (Product.DATA_CATALOG, Feature.QUERY)
