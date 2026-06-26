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
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "attr", "value": "val_1"},
                            {"key": "attr_2", "value": "val_2"},
                        ],
                    },
                    {"type": "OR", "values": [{"key": "attr", "value": "val_2"}]},
                ],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.values[0], PropertyGroup)
    assert filter.property_groups.values[0].type == "AND"
    assert isinstance(filter.property_groups.values[0].values[0], Property)
    assert filter.property_groups.values[0].values[0].key == "attr"
    assert filter.property_groups.values[0].values[0].value == "val_1"
    assert isinstance(filter.property_groups.values[0].values[1], Property)
    assert filter.property_groups.values[0].values[1].key == "attr_2"
    assert filter.property_groups.values[0].values[1].value == "val_2"

    assert isinstance(filter.property_groups.values[1], PropertyGroup)
    assert filter.property_groups.values[1].type == "OR"
    assert isinstance(filter.property_groups.values[1].values[0], Property)
    assert filter.property_groups.values[1].values[0].key == "attr"
    assert filter.property_groups.values[1].values[0].value == "val_2"


def test_property_group_simple_parsing():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                ],
            }
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.values[0], Property)
    assert filter.property_groups.values[0].key == "attr"
    assert filter.property_groups.values[0].value == "val_1"
    assert isinstance(filter.property_groups.values[1], Property)
    assert filter.property_groups.values[1].key == "attr_2"
    assert filter.property_groups.values[1].value == "val_2"


def test_property_group_empty_parsing():
    filter = Filter(data={"properties": {}})

    assert filter.property_groups.type == "AND"
    assert filter.property_groups.values == []


def test_property_group_invalid_parsing():
    filter = Filter(
        data={
            "properties": {
                "type": "XaND",
                "values": [
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                ],
            }
        }
    )

    with pytest.raises(ValidationError):
        filter.property_groups  # noqa: B018


def test_property_group_promotes_mixed_property_and_group_lists():
    # A list mixing bare property dicts with nested groups must not abort parsing — each bare
    # property is promoted into a single-element AND group so the list is uniformly groups.
    # Malformed saved filters of this shape otherwise crashed async cohort recalculation.
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "or", "values": [{"key": "attr", "value": "val_1"}]},
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                    {"type": "OR", "values": []},
                ],
            }
        }
    )

    groups = filter.property_groups
    assert groups.type == "AND"

    nested_or, promoted_1, promoted_2, empty = groups.values
    assert isinstance(nested_or, PropertyGroup)
    assert isinstance(promoted_1, PropertyGroup)
    assert isinstance(promoted_2, PropertyGroup)
    assert isinstance(empty, PropertyGroup)

    assert nested_or.type == "OR"
    assert isinstance(nested_or.values[0], Property)
    assert nested_or.values[0].key == "attr"

    # bare properties promoted into single-element AND groups
    assert promoted_1.type == "AND"
    assert isinstance(promoted_1.values[0], Property)
    assert promoted_1.values[0].key == "attr"
    assert isinstance(promoted_2.values[0], Property)
    assert promoted_2.values[0].key == "attr_2"

    # empty nested group preserved (carries no criteria)
    assert empty.values == []


def test_property_multi_level_to_dict():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "attr", "value": "val_1"},
                            {"key": "attr_2", "value": "val_2"},
                        ],
                    },
                    {"type": "OR", "values": [{"key": "attr", "value": "val_2"}]},
                ],
            }
        }
    )

    assert filter.property_groups.to_dict() == {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {"key": "attr", "value": "val_1", "type": "event"},
                    {"key": "attr_2", "value": "val_2", "type": "event"},
                ],
            },
            {
                "type": "OR",
                "values": [{"key": "attr", "value": "val_2", "type": "event"}],
            },
        ],
    }


def test_property_group_simple_to_dict():
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                ],
            }
        }
    )

    assert filter.property_groups.to_dict() == {
        "type": "AND",
        "values": [
            {"key": "attr", "value": "val_1", "type": "event"},
            {"key": "attr_2", "value": "val_2", "type": "event"},
        ],
    }


def test_property_group_simple_json_parsing():
    filter = Filter(
        data={
            "properties": json.dumps(
                {
                    "type": "AND",
                    "values": [
                        {"key": "attr", "value": "val_1"},
                        {"key": "attr_2", "value": "val_2"},
                    ],
                }
            )
        }
    )

    assert filter.property_groups.type == "AND"

    assert isinstance(filter.property_groups.values[0], Property)
    assert filter.property_groups.values[0].key == "attr"
    assert filter.property_groups.values[0].value == "val_1"
    assert isinstance(filter.property_groups.values[1], Property)
    assert filter.property_groups.values[1].key == "attr_2"
    assert filter.property_groups.values[1].value == "val_2"


def test_property_group_multi_level_json_parsing():
    filter = Filter(
        data={
            "properties": json.dumps(
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "attr", "value": "val_1"},
                                {"key": "attr_2", "value": "val_2"},
                            ],
                        },
                        {"type": "OR", "values": [{"key": "attr", "value": "val_2"}]},
                    ],
                }
            )
        }
    )

    assert filter.property_groups.type == "AND"
    assert isinstance(filter.property_groups.values[0], PropertyGroup)
    assert filter.property_groups.values[0].type == "AND"

    assert isinstance(filter.property_groups.values[0].values[0], Property)
    assert filter.property_groups.values[0].values[0].key == "attr"
    assert filter.property_groups.values[0].values[0].value == "val_1"
    assert isinstance(filter.property_groups.values[0].values[1], Property)
    assert filter.property_groups.values[0].values[1].key == "attr_2"
    assert filter.property_groups.values[0].values[1].value == "val_2"

    assert isinstance(filter.property_groups.values[1], PropertyGroup)
    assert filter.property_groups.values[1].type == "OR"
    assert isinstance(filter.property_groups.values[1].values[0], Property)
    assert filter.property_groups.values[1].values[0].key == "attr"
    assert filter.property_groups.values[1].values[0].value == "val_2"
