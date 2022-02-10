import json

from posthog.models import Filter
from posthog.models.property import Property, PropertyGroup


def test_property_group_multi_level_parsing():
    filter = Filter(
        data={
            "property_groups": {
                "type": "AND",
                "properties": [
                    {
                        "type": "AND",
                        "properties": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
                    },
                    {"type": "OR", "properties": [{"key": "attr", "value": "val_2"}]},
                ],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.properties[0], PropertyGroup)
    assert filter.property_groups.properties[0].type == "AND"
    assert isinstance(filter.property_groups.properties[0].properties[0], Property)
    assert filter.property_groups.properties[0].properties[0].key == "attr"
    assert filter.property_groups.properties[0].properties[0].value == "val_1"
    assert isinstance(filter.property_groups.properties[0].properties[1], Property)
    assert filter.property_groups.properties[0].properties[1].key == "attr_2"
    assert filter.property_groups.properties[0].properties[1].value == "val_2"

    assert isinstance(filter.property_groups.properties[1], PropertyGroup)
    assert filter.property_groups.properties[1].type == "OR"
    assert isinstance(filter.property_groups.properties[1].properties[0], Property)
    assert filter.property_groups.properties[1].properties[0].key == "attr"
    assert filter.property_groups.properties[1].properties[0].value == "val_2"


def test_property_group_simple_parsing():
    filter = Filter(
        data={
            "property_groups": {
                "type": "AND",
                "properties": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.properties[0], Property)
    assert filter.property_groups.properties[0].key == "attr"
    assert filter.property_groups.properties[0].value == "val_1"
    assert isinstance(filter.property_groups.properties[1], Property)
    assert filter.property_groups.properties[1].key == "attr_2"
    assert filter.property_groups.properties[1].value == "val_2"


def test_property_group_empty_parsing():
    filter = Filter(data={"property_groups": {}})

    assert filter.property_groups.type == "AND"
    assert filter.property_groups.properties == []


def test_property_group_simple_json_parsing():
    filter = Filter(
        data={
            "property_groups": json.dumps(
                {"type": "AND", "properties": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}]}
            )
        }
    )

    assert filter.property_groups.type == "AND"

    assert isinstance(filter.property_groups.properties[0], Property)
    assert filter.property_groups.properties[0].key == "attr"
    assert filter.property_groups.properties[0].value == "val_1"
    assert isinstance(filter.property_groups.properties[1], Property)
    assert filter.property_groups.properties[1].key == "attr_2"
    assert filter.property_groups.properties[1].value == "val_2"


def test_property_group_multi_level_json_parsing():
    filter = Filter(
        data={
            "property_groups": json.dumps(
                {
                    "type": "AND",
                    "properties": [
                        {
                            "type": "AND",
                            "properties": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
                        },
                        {"type": "OR", "properties": [{"key": "attr", "value": "val_2"}]},
                    ],
                }
            )
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.properties[0], PropertyGroup)
    assert filter.property_groups.properties[0].type == "AND"

    assert isinstance(filter.property_groups.properties[0].properties[0], Property)
    assert filter.property_groups.properties[0].properties[0].key == "attr"
    assert filter.property_groups.properties[0].properties[0].value == "val_1"
    assert isinstance(filter.property_groups.properties[0].properties[1], Property)
    assert filter.property_groups.properties[0].properties[1].key == "attr_2"
    assert filter.property_groups.properties[0].properties[1].value == "val_2"

    assert isinstance(filter.property_groups.properties[1], PropertyGroup)
    assert filter.property_groups.properties[1].type == "OR"
    assert isinstance(filter.property_groups.properties[1].properties[0], Property)
    assert filter.property_groups.properties[1].properties[0].key == "attr"
    assert filter.property_groups.properties[1].properties[0].value == "val_2"
