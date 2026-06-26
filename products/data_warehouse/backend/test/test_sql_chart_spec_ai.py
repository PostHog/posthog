from posthog.test.base import BaseTest
from unittest.mock import PropertyMock, patch

from django.test import override_settings

from langchain_core.runnables import RunnableLambda

from products.data_warehouse.backend.sql_chart_spec_ai import (
    CHART_MAPPING_SCHEMA,
    ChartSpecMapping,
    SQLChartSpecGenerator,
    build_fallback_chart_mapping,
    infer_semantic_type,
)

TIMESERIES_PAYLOAD = {
    "query": "select day, signups from events",
    "prompt": "show signups over time",
    "columns": [
        {"name": "day", "type": "DateTime", "semanticType": "temporal", "sampleValues": ["2026-01-01"]},
        {"name": "signups", "type": "Int64", "semanticType": "quantitative", "sampleValues": [10, 20]},
    ],
    "rowCount": 2,
}


@override_settings(IN_UNIT_TESTING=True)
class TestSQLChartSpecGenerator(BaseTest):
    async def test_agenerate_parses_structured_mapping(self):
        generator = SQLChartSpecGenerator(self.team, self.user)
        canned = ChartSpecMapping(
            chartType="timeSeriesLine",
            xColumn="day",
            series=[{"column": "signups", "label": "Signups"}],
            narrative="Signups are rising.",
        )
        with patch.object(SQLChartSpecGenerator, "_model", new_callable=PropertyMock) as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: {"mapping": canned.model_dump()})
            mapping = await generator.agenerate(TIMESERIES_PAYLOAD)
        assert isinstance(mapping, ChartSpecMapping)
        assert mapping.chartType == "timeSeriesLine"
        assert mapping.xColumn == "day"
        assert mapping.series[0].column == "signups"

    def test_fallback_picks_temporal_x_and_numeric_series(self):
        mapping = build_fallback_chart_mapping(TIMESERIES_PAYLOAD)
        assert mapping.xColumn == "day"
        assert [s.column for s in mapping.series] == ["signups"]
        assert mapping.chartType == "timeSeriesLine"

    def test_fallback_pie_when_prompt_asks(self):
        payload = {
            "prompt": "pie of revenue by country",
            "columns": [
                {"name": "country", "type": "String", "semanticType": "nominal", "sampleValues": ["US"]},
                {"name": "revenue", "type": "Float64", "semanticType": "quantitative", "sampleValues": [100.0]},
            ],
            "rowCount": 1,
        }
        mapping = build_fallback_chart_mapping(payload)
        assert mapping.chartType == "pie"
        assert mapping.xColumn == "country"

    def test_infer_semantic_type(self):
        assert infer_semantic_type("DateTime64") == "temporal"
        assert infer_semantic_type("Int64") == "quantitative"
        assert infer_semantic_type("String") == "nominal"
        assert infer_semantic_type(None) == "nominal"

    def test_schema_is_dereferenced_and_wraps_mapping(self):
        params = CHART_MAPPING_SCHEMA["parameters"]
        assert params["required"] == ["mapping"]
        assert "$defs" not in params["properties"]["mapping"]
