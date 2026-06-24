from typing import cast

from posthog.test.base import BaseTest

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Filter
from posthog.models.property import Property


class TestFilter(BaseTest):
    def test_old_style_properties(self):
        filter = Filter(data={"properties": {"$browser__is_not": "IE7", "$OS": "Mac"}})
        self.assertEqual(cast(Property, filter.property_groups.values[0]).key, "$browser")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).operator, "is_not")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).value, "IE7")
        self.assertEqual(cast(Property, filter.property_groups.values[0]).type, "event")
        self.assertEqual(cast(Property, filter.property_groups.values[1]).key, "$OS")
        self.assertEqual(cast(Property, filter.property_groups.values[1]).operator, None)
        self.assertEqual(cast(Property, filter.property_groups.values[1]).value, "Mac")

    def test_to_dict(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "display": "ActionsLineGraph",
                "compare": True,
                "interval": "",
                "actions": [],
                "date_from": "2020-01-01T20:00:00Z",
                "search": "query",
                "client_query_id": "123",
            }
        )
        self.assertCountEqual(
            list(filter.to_dict().keys()),
            [
                "events",
                "display",
                "compare",
                "insight",
                "date_from",
                "interval",
                "smoothing_intervals",
                "breakdown_attribution_type",
                "sampling_factor",
                "search",
                "breakdown_normalize_url",
            ],
        )

    def test_simplify_test_accounts(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        data = {"properties": [{"key": "attr", "value": "some_val"}]}

        filter = Filter(data=data, team=self.team)

        self.assertEqual(
            filter.properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                }
            },
        )
        self.assertTrue(filter.is_simplified)

        filter = Filter(data={**data, FILTER_TEST_ACCOUNTS: True}, team=self.team)

        self.assertEqual(
            filter.properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "value": "@posthog.com",
                                    "operator": "not_icontains",
                                    "type": "person",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                        },
                    ],
                }
            },
        )
        self.assertTrue(filter.is_simplified)

        self.assertEqual(
            filter.simplify(self.team).properties_to_dict(),
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "value": "@posthog.com",
                                    "operator": "not_icontains",
                                    "type": "person",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "attr", "value": "some_val", "type": "event"}],
                        },
                    ],
                }
            },
        )
