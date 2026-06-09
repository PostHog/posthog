from posthog.test.base import BaseTest

from pydantic import ValidationError

from posthog.schema import (
    AssistantFunnelsDataWarehouseNode,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FunnelsDataWarehouseNode,
)

from ee.hogai.utils.helpers import cast_assistant_query


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

    def _dw_step(self, custom_name: str) -> AssistantFunnelsDataWarehouseNode:
        return AssistantFunnelsDataWarehouseNode(
            custom_name=custom_name,
            id="invoices",
            table_name="invoices",
            id_field="id",
            timestamp_field="created_at",
            aggregation_target_field="customer_id",
        )

    def test_funnel_accepts_data_warehouse_steps(self):
        query = AssistantFunnelsQuery(series=[self._dw_step("First invoice"), self._dw_step("Paid invoice")])

        casted = cast_assistant_query(query)

        self.assertEqual(len(casted.series), 2)
        for step in casted.series:
            self.assertIsInstance(step, FunnelsDataWarehouseNode)
            self.assertEqual(step.kind, "FunnelsDataWarehouseNode")
            self.assertEqual(step.table_name, "invoices")
            self.assertEqual(step.aggregation_target_field, "customer_id")

    def test_funnel_accepts_mixed_event_and_data_warehouse_steps(self):
        query = AssistantFunnelsQuery(series=[{"event": "signed_up"}, self._dw_step("First invoice")])

        casted = cast_assistant_query(query)

        self.assertEqual(casted.series[0].kind, "EventsNode")
        self.assertIsInstance(casted.series[1], FunnelsDataWarehouseNode)
