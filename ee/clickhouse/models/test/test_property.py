from typing import Any, cast

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.constants import PropertyOperatorType
from posthog.models.property import Property
from posthog.models.property.util import PropertyGroup, get_property_string_expr

from ee.clickhouse.materialized_columns.columns import materialize


class TestPropDenormalized(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_get_property_string_expr(self):
        string_expr = get_property_string_expr("events", "some_non_mat_prop", "'some_non_mat_prop'", "properties")
        self.assertEqual(
            string_expr,
            (
                "replaceRegexpAll(JSONExtractRaw(properties, 'some_non_mat_prop'), '^\"|\"$', '')",
                False,
            ),
        )

        string_expr = get_property_string_expr(
            "events",
            "some_non_mat_prop",
            "'some_non_mat_prop'",
            "properties",
            table_alias="e",
        )
        self.assertEqual(
            string_expr,
            (
                "replaceRegexpAll(JSONExtractRaw(e.properties, 'some_non_mat_prop'), '^\"|\"$', '')",
                False,
            ),
        )

        materialize("events", "some_mat_prop")
        string_expr = get_property_string_expr("events", "some_mat_prop", "'some_mat_prop'", "properties")
        self.assertEqual(string_expr, ('"mat_some_mat_prop"', True))

        string_expr = get_property_string_expr(
            "events", "some_mat_prop", "'some_mat_prop'", "properties", table_alias="e"
        )
        self.assertEqual(string_expr, ('e."mat_some_mat_prop"', True))

        materialize("events", "some_mat_prop2", table_column="person_properties")
        materialize("events", "some_mat_prop3", table_column=cast(Any, "group2_properties"))
        string_expr = get_property_string_expr(
            "events",
            "some_mat_prop2",
            "x",
            "properties",
            materialised_table_column="person_properties",
        )
        self.assertEqual(string_expr, ('"mat_pp_some_mat_prop2"', True))


def test_combine_group_properties():
    propertyA = Property(key="a", operator="exact", value=["a", "b", "c"])
    propertyB = Property(key="b", operator="exact", value=["d", "e", "f"])
    propertyC = Property(key="c", operator="exact", value=["g", "h", "i"])
    propertyD = Property(key="d", operator="exact", value=["j", "k", "l"])

    property_group = PropertyGroup(PropertyOperatorType.OR, [propertyA, propertyB])

    combined_group = property_group.combine_properties(PropertyOperatorType.AND, [propertyC, propertyD])
    assert combined_group.to_dict() == {
        "type": "AND",
        "values": [
            {
                "type": "OR",
                "values": [
                    {
                        "key": "a",
                        "operator": "exact",
                        "value": ["a", "b", "c"],
                        "type": "event",
                    },
                    {
                        "key": "b",
                        "operator": "exact",
                        "value": ["d", "e", "f"],
                        "type": "event",
                    },
                ],
            },
            {
                "type": "AND",
                "values": [
                    {
                        "key": "c",
                        "operator": "exact",
                        "value": ["g", "h", "i"],
                        "type": "event",
                    },
                    {
                        "key": "d",
                        "operator": "exact",
                        "value": ["j", "k", "l"],
                        "type": "event",
                    },
                ],
            },
        ],
    }

    combined_group = property_group.combine_properties(PropertyOperatorType.OR, [propertyC, propertyD])
    assert combined_group.to_dict() == {
        "type": "OR",
        "values": [
            {
                "type": "OR",
                "values": [
                    {
                        "key": "a",
                        "operator": "exact",
                        "value": ["a", "b", "c"],
                        "type": "event",
                    },
                    {
                        "key": "b",
                        "operator": "exact",
                        "value": ["d", "e", "f"],
                        "type": "event",
                    },
                ],
            },
            {
                "type": "AND",
                "values": [
                    {
                        "key": "c",
                        "operator": "exact",
                        "value": ["g", "h", "i"],
                        "type": "event",
                    },
                    {
                        "key": "d",
                        "operator": "exact",
                        "value": ["j", "k", "l"],
                        "type": "event",
                    },
                ],
            },
        ],
    }

    combined_group = property_group.combine_properties(PropertyOperatorType.OR, [])
    assert combined_group.to_dict() == {
        "type": "OR",
        "values": [
            {
                "key": "a",
                "operator": "exact",
                "value": ["a", "b", "c"],
                "type": "event",
            },
            {
                "key": "b",
                "operator": "exact",
                "value": ["d", "e", "f"],
                "type": "event",
            },
        ],
    }

    combined_group = PropertyGroup(PropertyOperatorType.AND, cast(list[Property], [])).combine_properties(
        PropertyOperatorType.OR, [propertyC, propertyD]
    )
    assert combined_group.to_dict() == {
        "type": "AND",
        "values": [
            {
                "key": "c",
                "operator": "exact",
                "value": ["g", "h", "i"],
                "type": "event",
            },
            {
                "key": "d",
                "operator": "exact",
                "value": ["j", "k", "l"],
                "type": "event",
            },
        ],
    }
