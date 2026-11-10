from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import EventPropertyFilter

from posthog.models.team import Team

from products.dashboards.backend.widget_specs.common import WidgetDashboardFilterKind
from products.dashboards.backend.widgets.dashboard_filters import (
    NO_DASHBOARD_FILTERS,
    WidgetDashboardFilters,
    build_widget_dashboard_filters,
    parse_widget_datetime,
)
from products.dashboards.backend.widgets.widget_filters import (
    build_event_property_filters_from_widget_filters,
    build_property_group_filter_from_widget_filters,
    validate_widget_filters,
)


class TestWidgetFilters(SimpleTestCase):
    @parameterized.expand(
        [
            ("string", "nope"),
            ("int", 123),
            ("list", []),
        ]
    )
    def test_validate_widget_filters_rejects_invalid_shape(self, _label: str, widget_filters: object) -> None:
        with self.assertRaises(DRFValidationError):
            validate_widget_filters({"widgetFilters": widget_filters})

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
        assert validated["qf-1"].propertyName == "$environment"

    def test_build_property_group_filter_from_widget_filters(self) -> None:
        widget_filters = validate_widget_filters(
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
        filter_group = build_property_group_filter_from_widget_filters(widget_filters)
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
        widget_filters = validate_widget_filters(
            {
                "widgetFilters": {
                    "qf-1": {
                        "filterId": "qf-1",
                        "propertyName": "$browser",
                        "optionId": "opt-1",
                        "operator": "exact",
                        "value": "Chrome",
                    }
                }
            }
        )
        property_filters = build_event_property_filters_from_widget_filters(widget_filters)
        assert property_filters is not None
        assert property_filters[0]["key"] == "$browser"


def _event_filter(key: str, value: str | None, operator: str = "exact") -> dict:
    return {"type": "event", "key": key, "operator": operator, **({"value": [value]} if value else {})}


def _browser(value: str) -> dict:
    return _event_filter("$browser", value)


class TestBuildWidgetDashboardFilters(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "every_kind_supported",
                frozenset({"date_range", "filter_test_accounts", "properties"}),
                None,
                WidgetDashboardFilters(
                    date_from="-30d",
                    date_to="-1d",
                    filter_test_accounts=True,
                    properties=({"type": "event", "key": "$browser", "operator": "exact", "value": ["Chrome"]},),
                ),
            ),
            (
                "unsupported_kinds_dropped",
                frozenset({"date_range"}),
                None,
                WidgetDashboardFilters(date_from="-30d", date_to="-1d"),
            ),
            (
                "tile_ignores_dashboard_filters",
                frozenset({"date_range", "filter_test_accounts", "properties"}),
                {"ignoreDashboardFilters": True},
                NO_DASHBOARD_FILTERS,
            ),
            (
                "tile_date_range_wins",
                frozenset({"date_range"}),
                {"date_from": "-3d"},
                WidgetDashboardFilters(date_from="-3d"),
            ),
        ]
    )
    def test_build_widget_dashboard_filters(
        self,
        _name: str,
        supported: frozenset[WidgetDashboardFilterKind],
        tile_filters_overrides: dict | None,
        expected: WidgetDashboardFilters,
    ) -> None:
        dashboard_filters = {
            "date_from": "-30d",
            "date_to": "-1d",
            "filterTestAccounts": True,
            "properties": {
                "type": "AND",
                "values": [{"type": "event", "key": "$browser", "operator": "exact", "value": ["Chrome"]}],
            },
        }

        self.assertEqual(
            build_widget_dashboard_filters(dashboard_filters, tile_filters_overrides, supported),
            expected,
        )

    @parameterized.expand(
        [
            (
                "contradicted_widget_filter_dropped",
                [_browser("Safari"), _event_filter("$os", "Mac")],
                ["$os", "$browser"],
            ),
            ("compatible_widget_filter_kept", [_event_filter("$browser", None, "is_set")], ["$browser", "$browser"]),
        ]
    )
    def test_with_properties(self, _name: str, widget_filters: list[dict], expected_keys: list[str]) -> None:
        merged = WidgetDashboardFilters(properties=(_browser("Chrome"),)).with_properties(widget_filters)

        self.assertEqual([prop["key"] for prop in merged], expected_keys)
        self.assertNotIn(_browser("Safari"), merged)

    @parameterized.expand(
        [
            ("all_time_replaced_for_widget", "all", "-90d", ("-90d", None)),
            ("all_time_kept_by_default", "all", None, ("all", None)),
            ("dashboard_range_wins", "-30d", "-90d", ("-30d", None)),
        ]
    )
    def test_resolve_date_range(
        self, _name: str, date_from: str, all_time_date_from: str | None, expected: tuple[str | None, str | None]
    ) -> None:
        filters = WidgetDashboardFilters(date_from=date_from)
        kwargs = {"all_time_date_from": all_time_date_from} if all_time_date_from else {}

        self.assertEqual(filters.resolve_date_range({"dateRange": {"date_from": "-1h"}}, "-7d", **kwargs), expected)

    @parameterized.expand(
        [
            ("calendar_day_upper_bound_is_inclusive", "2026-09-01", True, datetime(2026, 9, 1, 23, 59, 59, 999999)),
            ("calendar_day_lower_bound_starts_the_day", "2026-09-01", False, datetime(2026, 9, 1)),
            ("all_time_is_open", "all", True, None),
        ]
    )
    def test_parse_widget_datetime(self, _name: str, value: str, end_of_day: bool, expected: datetime | None) -> None:
        team = Team(timezone="UTC")

        parsed = parse_widget_datetime(value, team, end_of_day=end_of_day)

        self.assertEqual(parsed, expected.replace(tzinfo=ZoneInfo("UTC")) if expected else None)
