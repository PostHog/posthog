import pytest

from parameterized import parameterized

from products.customer_analytics.backend.logic.custom_property_definitions import (
    InvalidCustomPropertyOptions,
    normalize_options,
)
from products.customer_analytics.backend.models import DisplayType


def test_non_select_types_never_store_options():
    assert normalize_options(DisplayType.TEXT, [{"id": "x", "label": "A", "color": "preset-1"}]) is None


def test_select_keeps_sent_ids_and_assigns_missing_ones():
    result = normalize_options(
        DisplayType.SELECT,
        [
            {"id": "opt-1", "label": " Enterprise ", "color": "preset-1"},
            {"label": "Startup", "color": "preset-2"},
        ],
        existing_ids=frozenset({"opt-1"}),
    )

    assert result is not None
    assert result[0] == {"id": "opt-1", "label": "Enterprise", "color": "preset-1"}
    assert result[1]["label"] == "Startup"
    assert result[1]["id"]


@parameterized.expand(
    [
        ("no_options", None, "A select property needs at least one option."),
        ("empty_options", [], "A select property needs at least one option."),
        ("blank_label", [{"label": "  ", "color": "preset-1"}], "Option labels can't be blank."),
        (
            "duplicate_label",
            [{"label": "A", "color": "preset-1"}, {"label": "A", "color": "preset-2"}],
            "Duplicate option label: 'A'.",
        ),
        (
            "duplicate_after_trim",
            [{"label": "A", "color": "preset-1"}, {"label": " A ", "color": "preset-2"}],
            "Duplicate option label: 'A'.",
        ),
        ("invalid_color", [{"label": "A", "color": "chartreuse"}], "Invalid option color: 'chartreuse'."),
        (
            "unknown_id",
            [{"id": "made-up", "label": "A", "color": "preset-1"}],
            "Option ids are assigned by the server; omit them for new options.",
        ),
    ]
)
def test_select_rejects_invalid_options(_name, options, expected_error):
    with pytest.raises(InvalidCustomPropertyOptions) as err:
        normalize_options(DisplayType.SELECT, options)

    assert str(err.value) == expected_error
