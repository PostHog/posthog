import json

import pytest
from rest_framework.exceptions import ValidationError

from posthog.models import Filter
from posthog.models.property import Property, PropertyGroup


def test_property_group_multi_level_parsing():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "groups": [
                    {
                        "type": "AND",
                        "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
                    },
                    {"type": "OR", "groups": [{"key": "attr", "value": "val_2"}]},
                ],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.groups[0], PropertyGroup)
    assert filter.property_groups.groups[0].type == "AND"
    assert isinstance(filter.property_groups.groups[0].groups[0], Property)
    assert filter.property_groups.groups[0].groups[0].key == "attr"
    assert filter.property_groups.groups[0].groups[0].value == "val_1"
    assert isinstance(filter.property_groups.groups[0].groups[1], Property)
    assert filter.property_groups.groups[0].groups[1].key == "attr_2"
    assert filter.property_groups.groups[0].groups[1].value == "val_2"

    assert isinstance(filter.property_groups.groups[1], PropertyGroup)
    assert filter.property_groups.groups[1].type == "OR"
    assert isinstance(filter.property_groups.groups[1].groups[0], Property)
    assert filter.property_groups.groups[1].groups[0].key == "attr"
    assert filter.property_groups.groups[1].groups[0].value == "val_2"


def test_property_group_simple_parsing():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.groups[0], Property)
    assert filter.property_groups.groups[0].key == "attr"
    assert filter.property_groups.groups[0].value == "val_1"
    assert isinstance(filter.property_groups.groups[1], Property)
    assert filter.property_groups.groups[1].key == "attr_2"
    assert filter.property_groups.groups[1].value == "val_2"


def test_property_group_empty_parsing():
    filter = Filter(data={"properties": {}})

    assert filter.property_groups.type == "AND"
    assert filter.property_groups.groups == []


def test_property_group_invalid_parsing():

    filter = Filter(
        data={
            "properties": {
                "type": "XaND",
                "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"},],
            }
        }
    )

    with pytest.raises(ValidationError):
        filter.property_groups


def test_property_group_includes_unhomogenous_groups():

    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "groups": [
                    {"type": "or", "groups": [{"key": "attr", "value": "val_1"}]},
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                    {"type": "OR", "groups": []},
                ],
            }
        }
    )

    with pytest.raises(ValidationError):
        filter.property_groups


def test_property_multi_level_to_dict():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "groups": [
                    {
                        "type": "AND",
                        "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
                    },
                    {"type": "OR", "groups": [{"key": "attr", "value": "val_2"}]},
                ],
            }
        }
    )

    assert filter.property_groups.to_dict() == {
        "type": "AND",
        "groups": [
            {
                "type": "AND",
                "groups": [
                    {"key": "attr", "value": "val_1", "operator": None, "type": "event"},
                    {"key": "attr_2", "value": "val_2", "operator": None, "type": "event"},
                ],
            },
            {"type": "OR", "groups": [{"key": "attr", "value": "val_2", "operator": None, "type": "event"}]},
        ],
    }


def test_property_group_simple_to_dict():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
            }
        }
    )

    assert filter.property_groups.to_dict() == {
        "type": "AND",
        "groups": [
            {"key": "attr", "value": "val_1", "operator": None, "type": "event"},
            {"key": "attr_2", "value": "val_2", "operator": None, "type": "event"},
        ],
    }


def test_property_group_simple_json_parsing():
    filter = Filter(
        data={
            "properties": json.dumps(
                {"type": "AND", "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],}
            )
        }
    )

    assert filter.property_groups.type == "AND"

    assert isinstance(filter.property_groups.groups[0], Property)
    assert filter.property_groups.groups[0].key == "attr"
    assert filter.property_groups.groups[0].value == "val_1"
    assert isinstance(filter.property_groups.groups[1], Property)
    assert filter.property_groups.groups[1].key == "attr_2"
    assert filter.property_groups.groups[1].value == "val_2"


def test_property_group_multi_level_json_parsing():
    filter = Filter(
        data={
            "properties": json.dumps(
                {
                    "type": "AND",
                    "groups": [
                        {
                            "type": "AND",
                            "groups": [{"key": "attr", "value": "val_1"}, {"key": "attr_2", "value": "val_2"}],
                        },
                        {"type": "OR", "groups": [{"key": "attr", "value": "val_2"}]},
                    ],
                }
            )
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.groups[0], PropertyGroup)
    assert filter.property_groups.groups[0].type == "AND"

    assert isinstance(filter.property_groups.groups[0].groups[0], Property)
    assert filter.property_groups.groups[0].groups[0].key == "attr"
    assert filter.property_groups.groups[0].groups[0].value == "val_1"
    assert isinstance(filter.property_groups.groups[0].groups[1], Property)
    assert filter.property_groups.groups[0].groups[1].key == "attr_2"
    assert filter.property_groups.groups[0].groups[1].value == "val_2"

    assert isinstance(filter.property_groups.groups[1], PropertyGroup)
    assert filter.property_groups.groups[1].type == "OR"
    assert isinstance(filter.property_groups.groups[1].groups[0], Property)
    assert filter.property_groups.groups[1].groups[0].key == "attr"
    assert filter.property_groups.groups[1].groups[0].value == "val_2"
