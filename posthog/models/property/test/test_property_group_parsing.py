import json
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import patch

from posthoganalytics.contexts import get_capture_exception_code_variables_context
from rest_framework.exceptions import ValidationError

from posthog.models.property import Property, PropertyGroup, PropertyValidationError
from posthog.models.property.parse import parse_property_group_data


@pytest.mark.parametrize("encode", [lambda data: data, json.dumps], ids=["dict", "json"])
def test_property_group_multi_level_parsing(encode: Callable[[dict[str, Any]], Any]):
    property_groups = parse_property_group_data(
        encode(
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
    )

    assert property_groups.type == "AND"
    assert isinstance(property_groups.values[0], PropertyGroup)
    assert property_groups.values[0].type == "AND"
    assert isinstance(property_groups.values[0].values[0], Property)
    assert property_groups.values[0].values[0].key == "attr"
    assert property_groups.values[0].values[0].value == "val_1"
    assert isinstance(property_groups.values[0].values[1], Property)
    assert property_groups.values[0].values[1].key == "attr_2"
    assert property_groups.values[0].values[1].value == "val_2"

    assert isinstance(property_groups.values[1], PropertyGroup)
    assert property_groups.values[1].type == "OR"
    assert isinstance(property_groups.values[1].values[0], Property)
    assert property_groups.values[1].values[0].key == "attr"
    assert property_groups.values[1].values[0].value == "val_2"


@pytest.mark.parametrize("encode", [lambda data: data, json.dumps], ids=["dict", "json"])
def test_property_group_simple_parsing(encode: Callable[[dict[str, Any]], Any]):
    property_groups = parse_property_group_data(
        encode(
            {
                "type": "AND",
                "values": [
                    {"key": "attr", "value": "val_1"},
                    {"key": "attr_2", "value": "val_2"},
                ],
            }
        )
    )

    assert property_groups.type == "AND"
    assert isinstance(property_groups.values[0], Property)
    assert property_groups.values[0].key == "attr"
    assert property_groups.values[0].value == "val_1"
    assert isinstance(property_groups.values[1], Property)
    assert property_groups.values[1].key == "attr_2"
    assert property_groups.values[1].value == "val_2"


def test_property_group_empty_parsing():
    property_groups = parse_property_group_data({})

    assert property_groups.type == "AND"
    assert property_groups.values == []


def test_property_group_invalid_parsing():
    data = {
        "type": "XaND",
        "values": [
            {"key": "attr", "value": "val_1"},
            {"key": "attr_2", "value": "val_2"},
        ],
    }

    with pytest.raises(ValidationError):
        parse_property_group_data(data)


def test_property_group_includes_unhomogenous_groups():
    data = {
        "type": "AND",
        "values": [
            {"type": "or", "values": [{"key": "attr", "value": "val_1"}]},
            {"key": "attr", "value": "val_1"},
            {"key": "attr_2", "value": "val_2"},
            {"type": "OR", "values": []},
        ],
    }

    with pytest.raises(ValidationError):
        parse_property_group_data(data)


def test_property_multi_level_to_dict():
    property_groups = parse_property_group_data(
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

    assert property_groups.to_dict() == {
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
    property_groups = parse_property_group_data(
        {
            "type": "AND",
            "values": [
                {"key": "attr", "value": "val_1"},
                {"key": "attr_2", "value": "val_2"},
            ],
        }
    )

    assert property_groups.to_dict() == {
        "type": "AND",
        "values": [
            {"key": "attr", "value": "val_1", "type": "event"},
            {"key": "attr_2", "value": "val_2", "type": "event"},
        ],
    }


@pytest.mark.parametrize(
    "invalid_property,expected_fields,expected_exception,expected_fingerprint",
    [
        # Behavioral leaf missing its required event_type: fails Property.__init__'s own
        # attr-presence checks (PropertyValidationError, raised directly).
        pytest.param(
            {"key": "$pageview", "type": "behavioral", "value": "performed_event"},
            ["key", "type", "value"],
            PropertyValidationError,
            "parse_properties.PropertyValidationError.behavioral.performed_event.event_type",
            id="missing_event_type",
        ),
        # Behavioral leaf with a value that doesn't match any known BehavioralPropertyType
        # (and has no alias): Property.__init__ used to KeyError here, which _parse_properties
        # didn't catch, crashing the whole parse instead of dropping-and-reporting this leaf.
        pytest.param(
            {"key": "$pageview", "type": "behavioral", "value": "not_a_real_behavior", "event_type": "events"},
            ["event_type", "key", "type", "value"],
            PropertyValidationError,
            "parse_properties.PropertyValidationError.behavioral.unknown.value",
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
            "parse_properties.ValidationError.group",
            id="invalid_group_type_index",
        ),
        # Aliased behavioral leaf with no time window: fails the conditional check, whose
        # message joins sets in hash order, so the fingerprint must come from the canonical value.
        pytest.param(
            {
                "key": "$pageview",
                "type": "behavioral",
                "value": "performed_event_multiple_times",
                "event_type": "events",
                "operator_value": 2,
            },
            ["event_type", "key", "operator_value", "type", "value"],
            PropertyValidationError,
            "parse_properties.PropertyValidationError.behavioral.performed_event_multiple",
            id="aliased_leaf_without_time_window",
        ),
        # Unrecognized property type: stored strings must not reach the fingerprint.
        pytest.param(
            {"key": "attr", "value": "x", "type": "not_a_type"},
            ["key", "type", "value"],
            PropertyValidationError,
            "parse_properties.PropertyValidationError.unknown.type",
            id="unknown_property_type",
        ),
    ],
)
def test_property_group_parsing_reports_and_skips_unparsable_property(
    invalid_property, expected_fields, expected_exception, expected_fingerprint
):
    # A property that fails to construct used to be dropped by a bare `except: continue`
    # with no visibility at all. It must still be dropped (callers across the codebase
    # rely on best-effort parsing of legacy/malformed data), but the failure must now be
    # reported — regardless of which internal check inside Property.__init__ rejected it.
    data = {
        "type": "AND",
        "values": [{"key": "attr", "value": "val_1"}, invalid_property],
    }

    with patch("posthog.models.property.parse.capture_exception") as mock_capture_exception:
        properties = parse_property_group_data(data).values

    assert len(properties) == 1
    assert isinstance(properties[0], Property)
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], expected_exception)
    assert kwargs["additional_properties"] == {
        "property_type": invalid_property["type"],
        "property_fields": expected_fields,
        "$exception_fingerprint": expected_fingerprint,
    }


def test_property_group_parsing_reports_non_mapping_property():
    # Old-style flat-list path: a non-mapping element (e.g. a bare string) fails at
    # `Property(**prop_params)` unpacking with TypeError, before __init__ even runs. The
    # grouped-properties path can't reach this: a non-mapping element trips the "cannot
    # contain both PropertyGroup and Property objects" check first.
    data = [{"key": "attr", "value": "val_1"}, "not-a-mapping"]

    with patch("posthog.models.property.parse.capture_exception") as mock_capture_exception:
        properties = parse_property_group_data(data).values

    assert len(properties) == 1
    assert isinstance(properties[0], Property)
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], TypeError)
    assert kwargs["additional_properties"] == {
        "property_type": None,
        "property_fields": None,
        "$exception_fingerprint": "parse_properties.TypeError.unknown",
    }


def test_property_group_parsing_disables_code_variable_capture_for_reported_exception():
    # capture_exception() forwards the exception object to PostHog's error-tracking SDK, which
    # has code-variable capture enabled globally: it would otherwise attach this frame's locals
    # -- including the malformed property's raw value/event_filters -- regardless of the
    # deliberately structure-only additional_properties above. Must be disabled for this call.
    observed_context_values = []

    def fake_capture_exception(error, additional_properties=None):
        observed_context_values.append(get_capture_exception_code_variables_context())

    data = [{"key": "attr", "value": "val_1"}, "not-a-mapping"]

    with patch(
        "posthog.models.property.parse.capture_exception", side_effect=fake_capture_exception
    ) as mock_capture_exception:
        _ = parse_property_group_data(data).values

    mock_capture_exception.assert_called_once()
    assert observed_context_values == [False]
