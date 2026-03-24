from posthog.test.base import BaseTest

from pydantic import ValidationError

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsQuery,
)


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

        with self.assertRaises(ValidationError):
            AssistantStickinessQuery(
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

    def test_stickiness_schema_series_properties_do_not_accept_arbitrary_strings(self):
        with self.assertRaises(ValidationError):
            AssistantStickinessQuery(
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

    def test_stickiness_schema_accepts_valid_query(self):
        query = AssistantStickinessQuery(
            series=[{"event": "$pageview"}],
        )
        self.assertEqual(query.kind, "StickinessQuery")
        self.assertEqual(len(query.series), 1)

    def test_stickiness_schema_accepts_valid_query_with_all_options(self):
        query = AssistantStickinessQuery(
            series=[{"event": "$pageview"}],
            interval="week",
            dateRange={"date_from": "-30d"},
            filterTestAccounts=True,
            stickinessFilter={"display": "ActionsBar", "showLegend": True, "showValuesOnSeries": True},
            compareFilter={"compare": True},
            properties=[{"key": "$browser", "type": "event", "operator": "exact", "value": ["Chrome"]}],
        )
        self.assertEqual(query.kind, "StickinessQuery")
        self.assertEqual(query.interval, "week")
        self.assertTrue(query.filterTestAccounts)
        self.assertEqual(query.stickinessFilter.display, "ActionsBar")
        self.assertTrue(query.compareFilter.compare)

    def test_stickiness_schema_rejects_invalid_display_type(self):
        with self.assertRaises(ValidationError):
            AssistantStickinessQuery(
                series=[{"event": "$pageview"}],
                stickinessFilter={"display": "BoldNumber"},
            )

        with self.assertRaises(ValidationError):
            AssistantStickinessQuery(
                series=[{"event": "$pageview"}],
                stickinessFilter={"display": "WorldMap"},
            )

    def test_stickiness_schema_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            AssistantStickinessQuery(
                series=[{"event": "$pageview"}],
                unknownField="value",
            )
