import json

import pytest
from unittest.mock import patch

from posthoganalytics.contexts import get_capture_exception_code_variables_context
from rest_framework.exceptions import ValidationError

from posthog.models import Filter
from posthog.models.property import Property, PropertyValidationError


def test_correlation_property_values_returns_valid_properties():
    # Happy path unchanged: Property instances and well-formed dicts all construct, and
    # nothing is reported.
    existing = Property(key="attr", value="val_1", type="event")
    filter = Filter(
        data={
            "funnel_correlation_property_values": [
                existing,
                {"key": "attr_2", "value": "val_2", "type": "event"},
            ]
        }
    )

    with patch("posthog.models.filters.mixins.funnel.capture_exception") as mock_capture_exception:
        properties = filter.correlation_property_values

    assert properties is not None
    assert len(properties) == 2
    assert properties[0] is existing
    assert isinstance(properties[1], Property)
    assert properties[1].key == "attr_2"
    mock_capture_exception.assert_not_called()


def test_correlation_property_values_accepts_json_string_input():
    filter = Filter(
        data={
            "funnel_correlation_property_values": json.dumps(
                [
                    {"key": "attr", "value": "val_1", "type": "event"},
                    {"key": "$pageview", "type": "behavioral", "value": "performed_event"},
                ]
            )
        }
    )

    with patch("posthog.models.filters.mixins.funnel.capture_exception") as mock_capture_exception:
        properties = filter.correlation_property_values

    assert properties is not None
    assert len(properties) == 1
    assert properties[0].key == "attr"
    mock_capture_exception.assert_called_once()


def test_correlation_property_values_rejects_unparsable_json_string():
    # Pre-existing guard, unchanged: an unparsable JSON body is a hard validation error,
    # not a skip.
    filter = Filter(data={"funnel_correlation_property_values": "{not json"})

    with pytest.raises(ValidationError, match="Properties are unparsable!"):
        _ = filter.correlation_property_values


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
        # "group" property with an out-of-range group_type_index: fails via
        # validate_group_type_index as its native rest_framework ValidationError.
        pytest.param(
            {"key": "industry", "value": "tech", "type": "group", "group_type_index": 99},
            ["group_type_index", "key", "type", "value"],
            ValidationError,
            id="invalid_group_type_index",
        ),
    ],
)
def test_correlation_property_values_reports_and_skips_unparsable_property(
    invalid_property, expected_fields, expected_exception
):
    # A property that fails to construct used to be dropped by a bare `except: continue`
    # with no visibility at all. It must still be dropped (this path is best-effort parsing
    # for the correlation-persons display), but the failure must now be reported —
    # regardless of which internal check inside Property.__init__ rejected it.
    filter = Filter(
        data={
            "funnel_correlation_property_values": [
                {"key": "attr", "value": "val_1", "type": "event"},
                invalid_property,
            ]
        }
    )

    with patch("posthog.models.filters.mixins.funnel.capture_exception") as mock_capture_exception:
        properties = filter.correlation_property_values

    assert properties is not None
    assert len(properties) == 1
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], expected_exception)
    assert kwargs["additional_properties"] == {
        "property_type": invalid_property["type"],
        "property_fields": expected_fields,
    }


def test_correlation_property_values_reports_non_mapping_property():
    # A non-mapping element (e.g. a bare string) fails at `Property(**prop_params)`
    # unpacking with TypeError, before __init__ even runs.
    filter = Filter(
        data={
            "funnel_correlation_property_values": [{"key": "attr", "value": "val_1", "type": "event"}, "not-a-mapping"]
        }
    )

    with patch("posthog.models.filters.mixins.funnel.capture_exception") as mock_capture_exception:
        properties = filter.correlation_property_values

    assert properties is not None
    assert len(properties) == 1
    assert properties[0].key == "attr"

    mock_capture_exception.assert_called_once()
    args, kwargs = mock_capture_exception.call_args
    assert isinstance(args[0], TypeError)
    assert kwargs["additional_properties"] == {"property_type": None, "property_fields": None}


def test_correlation_property_values_disables_code_variable_capture_for_reported_exception():
    # capture_exception() forwards the exception object to PostHog's error-tracking SDK,
    # which has code-variable capture enabled globally: it would otherwise attach this
    # frame's locals — including the malformed property's raw value/event_filters —
    # regardless of the deliberately structure-only additional_properties above. Must be
    # disabled for this call.
    observed_context_values = []

    def fake_capture_exception(error, additional_properties=None):
        observed_context_values.append(get_capture_exception_code_variables_context())

    filter = Filter(
        data={
            "funnel_correlation_property_values": [
                {"key": "attr", "value": "val_1", "type": "event"},
                {"key": "$pageview", "type": "behavioral", "value": "performed_event"},
            ]
        }
    )

    with patch(
        "posthog.models.filters.mixins.funnel.capture_exception", side_effect=fake_capture_exception
    ) as mock_capture_exception:
        _ = filter.correlation_property_values

    mock_capture_exception.assert_called_once()
    assert observed_context_values == [False]
