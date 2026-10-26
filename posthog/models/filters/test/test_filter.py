from typing import cast

from posthog.test.base import BaseTest

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models.property import Property
from posthog.models.property.parse import expand_cohort_properties, parse_properties_for_team, parse_property_group_data

from products.cohorts.backend.models.cohort import Cohort


class TestFilter(BaseTest):
    def test_old_style_properties(self):
        property_groups = parse_property_group_data({"$browser__is_not": "IE7", "$OS": "Mac"})
        self.assertEqual(cast(Property, property_groups.values[0]).key, "$browser")
        self.assertEqual(cast(Property, property_groups.values[0]).operator, "is_not")
        self.assertEqual(cast(Property, property_groups.values[0]).value, "IE7")
        self.assertEqual(cast(Property, property_groups.values[0]).type, "event")
        self.assertEqual(cast(Property, property_groups.values[1]).key, "$OS")
        self.assertEqual(cast(Property, property_groups.values[1]).operator, None)
        self.assertEqual(cast(Property, property_groups.values[1]).value, "Mac")

    def test_test_accounts_are_folded_in(self):
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

        self.assertEqual(
            parse_properties_for_team(data, self.team).to_dict(),
            {
                "type": "AND",
                "values": [{"key": "attr", "value": "some_val", "type": "event"}],
            },
        )

        self.assertEqual(
            parse_properties_for_team({**data, FILTER_TEST_ACCOUNTS: True}, self.team).to_dict(),
            {
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
            },
        )

    def test_nested_groups_keep_their_shape(self):
        # A single-property group nested under a parent with several values keeps its level;
        # only a group that is its parent's sole value collapses.
        properties = {
            "type": "OR",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        {"type": "AND", "values": [{"type": "person", "key": "email", "value": ".com"}]},
                    ],
                },
                {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "value": "arg2"},
                        {"type": "person", "key": "email", "value": "arg3"},
                    ],
                },
            ],
        }

        self.assertEqual(
            expand_cohort_properties(parse_property_group_data(properties), self.team).to_dict(),
            {
                "type": "OR",
                "values": [
                    {"type": "OR", "values": [{"type": "person", "key": "email", "value": ".com"}]},
                    {
                        "type": "AND",
                        "values": [
                            {"type": "AND", "values": [{"type": "person", "key": "email", "value": "arg2"}]},
                            {"type": "AND", "values": [{"type": "person", "key": "email", "value": "arg3"}]},
                        ],
                    },
                ],
            },
        )

    def test_cohort_nested_in_a_group_is_expanded(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )

        properties = {
            "type": "AND",
            "values": [
                {"type": "OR", "values": [{"type": "cohort", "key": "id", "value": cohort.pk}]},
            ],
        }

        self.assertEqual(
            expand_cohort_properties(parse_property_group_data(properties), self.team).to_dict(),
            {"type": "AND", "values": [{"type": "person", "key": "email", "operator": "icontains", "value": ".com"}]},
        )
