from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.hogql.errors import ExposedHogQLError

from products.data_catalog.backend.logic.certifications import propose_certification
from products.data_catalog.backend.logic.exceptions import MetricDrifted
from products.data_catalog.backend.logic.execution import run_metric
from products.data_catalog.backend.logic.metrics import approve_metric, upsert_metric
from products.data_catalog.backend.logic.relationships import propose_relationship
from products.product_analytics.backend.models.insight import Insight
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_HOGQL = {"kind": "HogQLQuery", "query": "select count() from events"}
_CAPTURE = "posthog.event_usage.posthoganalytics.capture"
_PROCESS_QUERY = "products.data_catalog.backend.logic.execution.process_query_dict"


def _catalog_calls(capture: MagicMock) -> list:
    return [c for c in capture.call_args_list if c.kwargs.get("event", "").startswith("data catalog")]


class TestDataCatalogAnalytics(BaseTest):
    @patch(_CAPTURE)
    def test_system_writes_emit_team_keyed_events(self, capture: MagicMock) -> None:
        upsert_metric(team=self.team, user=None, name="mrr", description="d")
        table = DataWarehouseTable.objects.create(
            name="stripe_customers", format="Parquet", team=self.team, url_pattern="s3://bucket/x"
        )
        propose_certification(team=self.team, user=None, table_id=table.id)
        propose_relationship(
            team=self.team,
            user=None,
            source_table_name="events",
            source_table_key="properties.person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person_row",
        )

        calls = _catalog_calls(capture)
        assert {c.kwargs["event"] for c in calls} == {
            "data catalog metric created",
            "data catalog certification proposed",
            "data catalog relationship proposed",
        }
        for call in calls:
            assert call.kwargs["distinct_id"] == str(self.team.uuid)
            assert call.kwargs["properties"]["is_system"] is True

    @patch(_CAPTURE)
    def test_drifted_approve_emits_blocked_event_and_still_raises(self, capture: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.user, query=_HOGQL)
        metric = upsert_metric(
            team=self.team, user=self.user, name="mrr", description="d", source_insight_short_id=insight.short_id
        )
        Insight.objects.filter(pk=insight.pk).update(query={"kind": "HogQLQuery", "query": "select 1"})
        capture.reset_mock()

        with self.assertRaises(MetricDrifted):
            approve_metric(metric, self.user)

        events = [c.kwargs["event"] for c in _catalog_calls(capture)]
        assert events == ["data catalog metric approval blocked"]
        [blocked] = _catalog_calls(capture)
        assert blocked.kwargs["properties"]["reason"] == "drifted"

    @parameterized.expand(
        [
            ("definition_error", {"side_effect": ExposedHogQLError("no such table")}),
            ("invalid_query", {"return_value": {"results": None, "error": "does not validate"}}),
        ]
    )
    @patch(_CAPTURE)
    def test_failed_run_emits_run_failed_with_reason(
        self, expected_reason: str, process_query_behavior: dict, capture: MagicMock
    ) -> None:
        metric = upsert_metric(team=self.team, user=self.user, name="mrr", description="d", definition=_HOGQL)
        capture.reset_mock()

        with patch(_PROCESS_QUERY, **process_query_behavior):
            with self.assertRaises(ValidationError):
                run_metric(team=self.team, metric=metric, user=self.user)

        events = [c.kwargs["event"] for c in _catalog_calls(capture)]
        assert events == ["data catalog metric run failed"]
        [failed] = _catalog_calls(capture)
        assert failed.kwargs["properties"]["reason"] == expected_reason


class TestDataCatalogAnalyticsAttribution(APIBaseTest):
    @patch(_CAPTURE)
    def test_api_write_carries_transport_attribution(self, capture: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/data_catalog/metrics/", {"name": "mrr", "description": "d"}
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        [created] = [c for c in _catalog_calls(capture) if c.kwargs["event"] == "data catalog metric created"]
        assert created.kwargs["distinct_id"] == self.user.distinct_id
        properties = created.kwargs["properties"]
        assert properties["source"] == "web"
        assert properties["is_system"] is False
