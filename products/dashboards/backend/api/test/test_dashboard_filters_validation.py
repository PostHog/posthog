from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.dashboards.backend.api.dashboard import DashboardSerializer


class TestDashboardFiltersValidation(SimpleTestCase):
    def _validate(self, value):
        return DashboardSerializer._validated_filters(value)

    def test_rejects_non_dict(self):
        try:
            self._validate(["not", "a", "dict"])
        except serializers.ValidationError:
            return
        raise AssertionError("expected ValidationError")

    def test_rejects_non_list_non_group_properties(self):
        try:
            self._validate({"properties": "not-a-list-or-group"})
        except serializers.ValidationError:
            return
        raise AssertionError("expected ValidationError")

    def test_normalizes_property_group_dict_to_flat_list(self):
        # A PropertyGroupFilter dict must be flattened to the flat-list contract on write, so it can't
        # be persisted and later crash readers that assume the flat-list shape.
        prop = {"key": "$browser", "value": "Chrome", "type": "event"}
        result = self._validate(
            {"date_from": "-7d", "properties": {"type": "AND", "values": [{"type": "AND", "values": [prop]}]}}
        )
        assert result["properties"] == [prop]
        assert result["date_from"] == "-7d"

    def test_rejects_or_property_group(self):
        try:
            self._validate(
                {"properties": {"type": "OR", "values": [{"key": "$browser", "value": "Chrome", "type": "event"}]}}
            )
        except serializers.ValidationError:
            return
        raise AssertionError("expected ValidationError")


class TestDashboardTileFiltersOverridesValidation(SimpleTestCase):
    def test_normalizes_property_group_dict_on_tile_filters_overrides(self):
        # Tile `filters_overrides` is opaque JSON with the same properties shape ambiguity as dashboard
        # `filters`; a PropertyGroupFilter dict must be flattened to the flat-list contract on write.
        prop = {"key": "$browser", "value": "Chrome", "type": "event"}
        result = DashboardSerializer._extract_display_defaults(
            {"filters_overrides": {"date_from": "-7d", "properties": {"type": "AND", "values": [prop]}}}
        )
        assert result["filters_overrides"]["properties"] == [prop]
        assert result["filters_overrides"]["date_from"] == "-7d"

    def test_rejects_non_dict_tile_filters_overrides(self):
        with self.assertRaises(serializers.ValidationError):
            DashboardSerializer._extract_display_defaults({"filters_overrides": []})

    def test_allows_clearing_tile_filters_overrides(self):
        result = DashboardSerializer._extract_display_defaults({"filters_overrides": None})
        assert result["filters_overrides"] is None


class TestDashboardBreakdownColorsValidation(SimpleTestCase):
    def _field(self):
        # Read the field off the serializer rather than building one, so the cases bind to the shape
        # the endpoint actually validates against.
        return DashboardSerializer().fields["breakdown_colors"]

    @parameterized.expand(
        [
            # Both keys decide which value gets which color, so an entry without one can never apply.
            # Every shape here was accepted before and stored as colors that silently did nothing.
            ("value_and_color_in_snake_case", [{"breakdown_value": "good", "color": "#36a854"}]),
            ("hex_color_under_the_wrong_key", [{"breakdownValue": "good", "color": "#36a854"}]),
            ("missing_color_token", [{"breakdownValue": "Chrome"}]),
            ("missing_breakdown_value", [{"colorToken": "preset-1"}]),
            # A list of bare breakdown values instead of config objects.
            ("bare_breakdown_values", ["Chrome", "Firefox"]),
            # The shapes that crashed the dashboard scene on every load.
            ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}),
            ("empty_object", {}),
        ]
    )
    def test_rejects(self, _name, value):
        with self.assertRaises(serializers.ValidationError):
            self._field().run_validation(value)

    @parameterized.expand(
        [
            ("minimal_entry", [{"breakdownValue": "Chrome", "colorToken": "preset-1"}]),
            (
                "every_key",
                [
                    {
                        "breakdownValue": "Chrome",
                        "colorToken": "preset-1",
                        "breakdownType": "event",
                        "breakdownProperty": "event::$browser",
                        "source": "manual",
                    }
                ],
            ),
            # A cleared color keeps its entry with a null token, so the key is required but the value
            # is not.
            ("null_color_token", [{"breakdownValue": "Chrome", "colorToken": None}]),
            # A breakdown value can legitimately be the empty string.
            ("blank_breakdown_value", [{"breakdownValue": "", "colorToken": "preset-1"}]),
            # Clearing every color, and the nullable column's own value.
            ("empty_list", []),
            ("null", None),
        ]
    )
    def test_accepts(self, _name, value):
        assert self._field().run_validation(value) == value

    @parameterized.expand(
        [
            ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}, []),
            ("empty_object", {}, []),
            ("double_encoded_list", '[{"breakdownValue": "Chrome", "colorToken": "preset-1"}]', []),
            ("bare_breakdown_values", ["Chrome", "Firefox"], []),
            (
                "entry_without_both_keys_beside_a_valid_one",
                [
                    {"breakdown_value": "good", "color": "#36a854"},
                    {"breakdownValue": "Chrome", "colorToken": "preset-1"},
                ],
                [{"breakdownValue": "Chrome", "colorToken": "preset-1"}],
            ),
        ]
    )
    def test_reads_stored_value_as(self, _name, stored, expected):
        assert self._field().to_representation(stored) == expected

    def test_read_keeps_keys_the_child_serializer_does_not_declare(self):
        # Reads deliberately bypass the child serializer, which would drop an undeclared key. Rendering
        # through the child would silently discard a key the frontend persists before this serializer
        # learns about it, and the loss would only show up as colors disappearing after a save.
        stored = [
            {
                "breakdownValue": "Chrome",
                "colorToken": "preset-1",
                "source": "manual",
                "breakdownProperty": "event::$browser",
                "aKeyThisSerializerDoesNotKnowAbout": "kept",
            }
        ]

        assert self._field().to_representation(stored) == stored
