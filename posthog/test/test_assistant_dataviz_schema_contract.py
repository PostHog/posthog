from django.test.testcases import SimpleTestCase

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    AssistantDataVisualizationAxisDisplaySettings,
    AssistantDataVisualizationChartSettings,
    AssistantDataVisualizationColumnDisplaySettings,
    AssistantDataVisualizationGoalLine,
    AssistantDataVisualizationMetricSettings,
    AssistantDataVisualizationTableSettings,
    AssistantInsightAxisDisplaySettings,
    AssistantInsightChartSettings,
    AssistantInsightColumnDisplaySettings,
    AssistantInsightGoalLine,
    AssistantInsightMetricSettings,
    ChartSettings,
    TableSettings,
)

# The assistant-facing DataVisualizationNode (produced by Max and the insight MCP tools) is
# validated on save against the real DataVisualizationNode, whose ChartSettings/TableSettings
# are `extra="forbid"`. Any assistant field not present on its real counterpart is rejected as
# an extra property, so a schema-following caller hits a validation error. These tests keep the
# advertised assistant fields a strict subset of what the API actually accepts.


class TestAssistantDataVizSchemaContract(SimpleTestCase):
    @parameterized.expand(
        [
            ("chart_settings", AssistantDataVisualizationChartSettings, ChartSettings),
            ("insight_tool_chart_settings", AssistantInsightChartSettings, ChartSettings),
            ("table_settings", AssistantDataVisualizationTableSettings, TableSettings),
        ]
    )
    def test_assistant_settings_are_accepted_by_real_settings(
        self, _name: str, assistant: type[BaseModel], real: type[BaseModel]
    ) -> None:
        extra = set(assistant.model_fields) - set(real.model_fields)
        self.assertEqual(
            extra,
            set(),
            f"{assistant.__name__} advertises fields {real.__name__} rejects: {sorted(extra)}",
        )

    @parameterized.expand(
        [
            ("chart_settings", AssistantInsightChartSettings, AssistantDataVisualizationChartSettings),
            ("goal_line", AssistantInsightGoalLine, AssistantDataVisualizationGoalLine),
            ("metric_settings", AssistantInsightMetricSettings, AssistantDataVisualizationMetricSettings),
            ("axis_display", AssistantInsightAxisDisplaySettings, AssistantDataVisualizationAxisDisplaySettings),
            ("column_display", AssistantInsightColumnDisplaySettings, AssistantDataVisualizationColumnDisplaySettings),
        ]
    )
    def test_insight_tool_copies_declare_the_same_fields_as_their_originals(
        self, _name: str, copy: type[BaseModel], original: type[BaseModel]
    ) -> None:
        self.assertEqual(
            set(copy.model_fields),
            set(original.model_fields),
            f"{copy.__name__} must declare the same fields as {original.__name__}",
        )
