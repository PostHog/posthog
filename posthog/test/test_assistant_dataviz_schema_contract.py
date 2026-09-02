from django.test.testcases import SimpleTestCase

from posthog.schema import (
    AssistantDataVisualizationChartSettings,
    AssistantDataVisualizationTableSettings,
    ChartSettings,
    TableSettings,
)

# The assistant-facing DataVisualizationNode (produced by Max and the insight MCP tools) is
# validated on save against the real DataVisualizationNode, whose ChartSettings/TableSettings
# are `extra="forbid"`. Any assistant field not present on its real counterpart is rejected as
# an extra property, so a schema-following caller hits a validation error. These tests keep the
# advertised assistant fields a strict subset of what the API actually accepts.


class TestAssistantDataVizSchemaContract(SimpleTestCase):
    def test_assistant_chart_settings_are_accepted_by_real_chart_settings(self) -> None:
        extra = set(AssistantDataVisualizationChartSettings.model_fields) - set(ChartSettings.model_fields)
        self.assertEqual(
            extra,
            set(),
            f"AssistantDataVisualizationChartSettings advertises fields ChartSettings rejects: {sorted(extra)}",
        )

    def test_assistant_table_settings_are_accepted_by_real_table_settings(self) -> None:
        extra = set(AssistantDataVisualizationTableSettings.model_fields) - set(TableSettings.model_fields)
        self.assertEqual(
            extra,
            set(),
            f"AssistantDataVisualizationTableSettings advertises fields TableSettings rejects: {sorted(extra)}",
        )
