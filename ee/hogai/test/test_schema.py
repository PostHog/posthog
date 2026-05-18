from posthog.test.base import BaseTest

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import (
    AssistantDataVisualizationDisplayType,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
)

from ee.hogai.tools.execute_sql.tool import ExecuteSQLToolArgs


class TestSchema(BaseTest):
    def test_schema_series_properties_do_not_accept_arbitrary_strings(self):
        """If this test fails, check the schema of `series.properties[].type`. It must be an enum."""

        with self.assertRaises(ValidationError):
            AssistantTrendsQuery(
                series=[
                    {
                        "event": "event",
                        "properties": [
                            {
                                "key": "random key",
                                "type": "MUST HAVE ENUMS HERE",
                                "operator": "exact",
                                "value": "random string",
                            }
                        ],
                    }
                ]
            )

        with self.assertRaises(ValidationError):
            AssistantFunnelsQuery(
                series=[
                    {
                        "event": "event",
                        "properties": [
                            {
                                "key": "random key",
                                "type": "MUST HAVE ENUMS HERE",
                                "operator": "exact",
                                "value": "random string",
                            }
                        ],
                    }
                ]
            )

    def test_schema_properties_do_not_accept_arbitrary_strings(self):
        """If this test fails, check the schema of `properties[].type`. It must be an enum."""

        with self.assertRaises(ValidationError):
            AssistantTrendsQuery(
                series=[{"event": "event"}],
                properties=[
                    {
                        "key": "random key",
                        "type": "MUST HAVE ENUMS HERE",
                        "operator": "exact",
                        "value": "random string",
                    }
                ],
            )

        with self.assertRaises(ValidationError):
            AssistantFunnelsQuery(
                series=[{"event": "event"}, {"event": "event"}],
                properties=[
                    {
                        "key": "random key",
                        "type": "MUST HAVE ENUMS HERE",
                        "operator": "exact",
                        "value": "random string",
                    }
                ],
            )

        with self.assertRaises(ValidationError):
            AssistantRetentionQuery(
                retentionFilter={
                    "returningEntity": {"name": "event"},
                    "targetEntity": {"name": "event"},
                },
                properties=[
                    {
                        "key": "random key",
                        "type": "MUST HAVE ENUMS HERE",
                        "operator": "exact",
                        "value": "random string",
                    }
                ],
            )

    @parameterized.expand([("ActionsBarValue",), ("ActionsPie",)])
    def test_assistant_data_visualization_display_supports_categorical_chart_types(self, value: str):
        # If this fails, an LLM-emitted display type silently disappears from a Max-generated
        # dashboard via the parallel task executor's swallow-and-continue path.
        ExecuteSQLToolArgs.model_validate(
            {
                "query": "SELECT event, count() FROM events GROUP BY event",
                "viz_title": "Event counts",
                "viz_description": "Count events by type",
                "display": value,
            }
        )
        assert AssistantDataVisualizationDisplayType(value)

    def test_assistant_multiple_breakdown_filter_routes_with_null_group_type_index(self):
        # The union has no discriminator hint, so pydantic falls back to best-match. A tolerant
        # LLM payload that always emits `group_type_index` (often null) must still route to the
        # generic variant via the `type` field instead of failing with `extra_forbidden`.
        query = AssistantTrendsQuery.model_validate(
            {
                "series": [{"event": "$pageview"}],
                "breakdownFilter": {
                    "breakdowns": [
                        {
                            "type": "person",
                            "property": "latest_utm_source",
                            "group_type_index": None,
                        }
                    ]
                },
            }
        )
        assert query.breakdownFilter is not None
        breakdown = query.breakdownFilter.breakdowns[0]
        assert breakdown.type == "person"
        assert breakdown.property == "latest_utm_source"
