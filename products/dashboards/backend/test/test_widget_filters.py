from django.test import TestCase

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import EventPropertyFilter

from products.dashboards.backend.widgets.widget_filters import (
    build_event_property_filters_from_widget_filters,
    build_property_group_filter_from_widget_filters,
    validate_widget_filters,
)


class TestWidgetFilters(TestCase):
    def test_validate_widget_filters_rejects_invalid_shape(self) -> None:
        with self.assertRaises(DRFValidationError):
            validate_widget_filters({"widgetFilters": "nope"})

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

    def test_validate_widget_filters_rejects_unknown_operator(self) -> None:
        with self.assertRaises(DRFValidationError):
            validate_widget_filters(
                {
                    "widgetFilters": {
                        "qf-1": {
                            "filterId": "qf-1",
                            "propertyName": "$environment",
                            "optionId": "opt-1",
                            "operator": "not_a_real_operator",
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
