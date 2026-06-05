from typing import cast

from django.test import TestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import EventPropertyFilter

from products.dashboards.backend.widgets.widget_config_types import WidgetListConfigInputBase
from products.dashboards.backend.widgets.widget_filters import (
    build_event_property_filters_from_widget_filters,
    build_property_group_filter_from_widget_filters,
    validate_widget_filters,
)


class TestWidgetFilters(TestCase):
    @parameterized.expand(
        [
            ("string", "nope"),
            ("int", 123),
            ("list", []),
        ]
    )
    def test_validate_widget_filters_rejects_invalid_shape(self, _label: str, widget_filters: object) -> None:
        with self.assertRaises(DRFValidationError):
            validate_widget_filters(cast(WidgetListConfigInputBase, {"widgetFilters": widget_filters}))

    def test_validate_widget_filters_normalizes_entries(self) -> None:
        validated = validate_widget_filters(
            {
                "widgetFilters": {
                    "qf-1": {
                        "filterId": "qf-1",
                        "propertyName": "$environment",
                        "optionId": "opt-1",
                        "operator": "exact",
                        "value": "production",
                    }
                }
            }
        )
        assert validated is not None
        assert validated["qf-1"]["propertyName"] == "$environment"

    def test_build_property_group_filter_from_widget_filters(self) -> None:
        filter_group = build_property_group_filter_from_widget_filters(
            {
                "qf-1": {
                    "filterId": "qf-1",
                    "propertyName": "$environment",
                    "optionId": "opt-1",
                    "operator": "exact",
                    "value": "production",
                }
            }
        )
        assert filter_group is not None
        property_filter = filter_group.values[0].values[0]
        assert isinstance(property_filter, EventPropertyFilter)
        assert property_filter.key == "$environment"

    @parameterized.expand(["not_a_real_operator", "bogus", "=="])
    def test_validate_widget_filters_rejects_unknown_operator(self, operator: str) -> None:
        with self.assertRaises(DRFValidationError):
            validate_widget_filters(
                {
                    "widgetFilters": {
                        "qf-1": {
                            "filterId": "qf-1",
                            "propertyName": "$environment",
                            "optionId": "opt-1",
                            "operator": operator,
                            "value": "production",
                        }
                    }
                }
            )

    def test_build_event_property_filters_from_widget_filters(self) -> None:
        property_filters = build_event_property_filters_from_widget_filters(
            {
                "qf-1": {
                    "filterId": "qf-1",
                    "propertyName": "$browser",
                    "optionId": "opt-1",
                    "operator": "exact",
                    "value": "Chrome",
                }
            }
        )
        assert property_filters is not None
        assert property_filters[0]["key"] == "$browser"
