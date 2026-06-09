from posthog.test.base import BaseTest

from pydantic import ValidationError

from posthog.schema import (
    AssistantFunnelsDataWarehouseNode,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FunnelsDataWarehouseNode,
    HogQLPropertyFilter,
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

    def _dw_step(self, custom_name: str, properties=None) -> AssistantFunnelsDataWarehouseNode:
        return AssistantFunnelsDataWarehouseNode(
            custom_name=custom_name,
            id="invoices",
            table_name="invoices",
            id_field="id",
            timestamp_field="created_at",
            aggregation_target_field="customer_id",
            properties=properties,
        )

    def test_funnel_accepts_data_warehouse_steps(self):
        query = AssistantFunnelsQuery(series=[self._dw_step("First invoice"), self._dw_step("Paid invoice")])

        casted = cast_assistant_query(query)

        self.assertEqual(len(casted.series), 2)
        for step in casted.series:
            self.assertIsInstance(step, FunnelsDataWarehouseNode)
            self.assertEqual(step.kind, "FunnelsDataWarehouseNode")
            # All fields the backend needs to actually run the query must survive the cast.
            self.assertEqual(step.id, "invoices")
            self.assertEqual(step.table_name, "invoices")
            self.assertEqual(step.id_field, "id")
            self.assertEqual(step.timestamp_field, "created_at")
            self.assertEqual(step.aggregation_target_field, "customer_id")

    def test_funnel_accepts_mixed_event_and_data_warehouse_steps(self):
        query = AssistantFunnelsQuery(series=[{"event": "signed_up"}, self._dw_step("First invoice")])

        casted = cast_assistant_query(query)

        self.assertEqual(casted.series[0].kind, "EventsNode")
        self.assertIsInstance(casted.series[1], FunnelsDataWarehouseNode)

    def test_funnel_data_warehouse_step_preserves_hogql_property_filter(self):
        """A HogQL property filter on a warehouse stage must survive the assistant→backend union-to-union cast."""

        query = AssistantFunnelsQuery(
            series=[
                self._dw_step(
                    "Startup plan invoice", properties=[{"type": "hogql", "key": "classification = 'startup'"}]
                ),
                self._dw_step(
                    "Standard plan invoice", properties=[{"type": "hogql", "key": "classification = 'standard'"}]
                ),
            ]
        )

        casted = cast_assistant_query(query)

        self.assertEqual(len(casted.series), 2)
        first = casted.series[0]
        self.assertIsInstance(first, FunnelsDataWarehouseNode)
        self.assertEqual(len(first.properties), 1)
        self.assertIsInstance(first.properties[0], HogQLPropertyFilter)
        self.assertEqual(first.properties[0].type, "hogql")
        self.assertEqual(first.properties[0].key, "classification = 'startup'")
        self.assertEqual(casted.series[1].properties[0].key, "classification = 'standard'")

    def test_funnel_data_warehouse_step_does_not_accept_arbitrary_property_types(self):
        """If this test fails, check the schema of the warehouse node's `properties[].type`. It must be an enum."""

        with self.assertRaises(ValidationError):
            self._dw_step(
                "First invoice",
                properties=[
                    {
                        "key": "random key",
                        "type": "MUST HAVE ENUMS HERE",
                        "operator": "exact",
                        "value": "random string",
                    }
                ],
            )
