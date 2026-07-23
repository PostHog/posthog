import json

import pytest
from unittest.mock import patch

from posthoganalytics.contexts import get_capture_exception_code_variables_context
from rest_framework.exceptions import ValidationError

from posthog.models import Filter
from posthog.models.property import Property, PropertyGroup, PropertyValidationError


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


def test_property_group_includes_unhomogenous_groups():
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

    with pytest.raises(ValidationError):
        filter.property_groups  # noqa: B018


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


@pytest.mark.parametrize(
    "invalid_property,expected_fields,expected_exception",
    [
        # Behavioral leaf missing its required event_type: fails Property.__init__'s own
        # attr-presence checks (PropertyValidationError, raised directly).
        pytest.param(
            {"key": "$pageview", "type": "behavioral", "value": "performed_event"},
            ["key", "type", "value"],
            PropertyValidationError,
            id="missing_event_type",
        ),
        # Behavioral leaf with a value that doesn't match any known BehavioralPropertyType
        # (and has no alias): Property.__init__ used to KeyError here, which _parse_properties
        # didn't catch, crashing the whole parse instead of dropping-and-reporting this leaf.
        pytest.param(
            {"key": "$pageview", "type": "behavioral", "value": "not_a_real_behavior", "event_type": "events"},
            ["event_type", "key", "type", "value"],
            PropertyValidationError,
            id="unknown_behavioral_value",
        ),
        # "group" property with an out-of-range group_type_index: fails via
        # validate_group_type_index, left as its native rest_framework ValidationError so
        # callers that construct Property() directly during serializer validation still get
        # a 400 for it.
        pytest.param(
            {"key": "industry", "value": "tech", "type": "group", "group_type_index": 99},
            ["group_type_index", "key", "type", "value"],
            ValidationError,
            id="invalid_group_type_index",
        ),
    ],
)
def test_property_group_parsing_reports_and_skips_unparsable_property(
    invalid_property, expected_fields, expected_exception
):
    # A property that fails to construct used to be dropped by a bare `except: continue`
    # with no visibility at all. It must still be dropped (callers across the codebase
    # rely on best-effort parsing of legacy/malformed data), but the failure must now be
    # reported — regardless of which internal check inside Property.__init__ rejected it.
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [{"key": "attr", "value": "val_1"}, invalid_property],
            }
        }
    )

    with patch("posthog.models.filters.mixins.property.capture_exception") as mock_capture_exception:
        properties = filter.property_groups.values

    assert len(properties) == 1
    assert isinstance(properties[0], Property)
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], expected_exception)
    assert kwargs["additional_properties"] == {
        "property_type": invalid_property["type"],
        "property_fields": expected_fields,
    }


def test_property_group_parsing_reports_non_mapping_property():
    # Old-style flat-list path: a non-mapping element (e.g. a bare string) fails at
    # `Property(**prop_params)` unpacking with TypeError, before __init__ even runs. The
    # grouped-properties path can't reach this: a non-mapping element trips the "cannot
    # contain both PropertyGroup and Property objects" check first.
    filter = Filter(data={"properties": [{"key": "attr", "value": "val_1"}, "not-a-mapping"]})

    with patch("posthog.models.filters.mixins.property.capture_exception") as mock_capture_exception:
        properties = filter.property_groups.values

    assert len(properties) == 1
    assert isinstance(properties[0], Property)
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], TypeError)
    assert kwargs["additional_properties"] == {"property_type": None, "property_fields": None}


def test_property_group_parsing_disables_code_variable_capture_for_reported_exception():
    # capture_exception() forwards the exception object to PostHog's error-tracking SDK, which
    # has code-variable capture enabled globally: it would otherwise attach this frame's locals
    # -- including the malformed property's raw value/event_filters -- regardless of the
    # deliberately structure-only additional_properties above. Must be disabled for this call.
    observed_context_values = []

    def fake_capture_exception(error, additional_properties=None):
        observed_context_values.append(get_capture_exception_code_variables_context())

    filter = Filter(data={"properties": [{"key": "attr", "value": "val_1"}, "not-a-mapping"]})

    with patch(
        "posthog.models.filters.mixins.property.capture_exception", side_effect=fake_capture_exception
    ) as mock_capture_exception:
        _ = filter.property_groups.values

    mock_capture_exception.assert_called_once()
    assert observed_context_values == [False]
