from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import AsyncMock

from products.data_warehouse.backend.sql_chart_spec_ai import ChartSpecMapping

TIMESERIES_REQUEST = {
    "query": "select day, signups from events",
    "prompt": "signups over time",
    "columns": [
        {"name": "day", "type": "DateTime", "semanticType": "temporal", "sampleValues": ["2026-01-01"]},
        {"name": "signups", "type": "Int64", "semanticType": "quantitative", "sampleValues": [10]},
    ],
    "sampleRows": [{"day": "2026-01-01", "signups": 10}],
    "rowCount": 1,
}


class TestSQLChartSpecAPI(APIBaseTest):
    def test_create_returns_generated_mapping(self):
        mapping = ChartSpecMapping(
            chartType="timeSeriesLine", xColumn="day", series=[{"column": "signups"}], narrative="Up."
        )
        with mock.patch(
            "products.data_warehouse.backend.presentation.views.sql_chart_spec.SQLChartSpecGenerator.agenerate",
            new=AsyncMock(return_value=mapping),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/sql_chart_spec/", TIMESERIES_REQUEST)

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["trace_id"].startswith("sql_chart_spec_")
        assert body["mapping"]["chartType"] == "timeSeriesLine"
        assert body["mapping"]["xColumn"] == "day"
        assert body["warnings"] == []

    def test_create_falls_back_when_generation_raises(self):
        with mock.patch(
            "products.data_warehouse.backend.presentation.views.sql_chart_spec.SQLChartSpecGenerator.agenerate",
            new=AsyncMock(side_effect=Exception("llm down")),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/sql_chart_spec/", TIMESERIES_REQUEST)

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["mapping"]["xColumn"] == "day"
        assert len(body["warnings"]) == 1

    def test_rejects_missing_columns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/sql_chart_spec/",
            {"query": "select 1", "prompt": "chart", "columns": [], "rowCount": 0},
        )
        assert response.status_code == 400
