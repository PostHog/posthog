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
    def _field(self, partial: bool) -> serializers.Field:
        # Read the field off the serializer rather than building one, so the cases bind to the shape
        # the endpoint actually validates against.
        #
        # Both modes, because DRF resolves `required` against the root serializer's partial flag
        # and a dashboard PATCH is partial.
        return DashboardSerializer(partial=partial).fields["breakdown_colors"]

    @parameterized.expand(
        [
            # Both keys decide which value gets which color, so an entry without them can never
            # apply. Callers wrote all of these while the field accepted any JSON.
            ("entry_under_snake_case_keys", [{"breakdown_value": "good", "color": "#36a854"}]),
            ("hex_color_under_the_wrong_key", [{"breakdownValue": "good", "color": "#36a854"}]),
            ("entry_missing_the_color_token", [{"breakdownValue": "Chrome"}]),
            ("entry_missing_the_breakdown_value", [{"colorToken": "preset-1"}]),
            ("bare_breakdown_values", ["Chrome", "Firefox"]),
            ("empty_entry", [{}]),
            # A token names a slot in the color theme, so any other string resolves to nothing.
            # getColorFromToken parses the N out of `preset-N`, and a hex value yields
            # theme['preset-NaN'].
            ("hex_color_token", [{"breakdownValue": "Chrome", "colorToken": "#3fb950"}]),
            ("unresolvable_color_token", [{"breakdownValue": "Chrome", "colorToken": "blue"}]),
            ("color_token_slot_zero", [{"breakdownValue": "Chrome", "colorToken": "preset-0"}]),
            ("color_token_non_ascii_digits", [{"breakdownValue": "Chrome", "colorToken": "preset-١"}]),
            # The two shapes that crashed the dashboard scene on every load.
            ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}),
            ("empty_object", {}),
        ]
    )
    def test_rejects(self, _name: str, value: object) -> None:
        for partial in (False, True):
            with self.subTest(partial=partial), self.assertRaises(serializers.ValidationError):
                self._field(partial=partial).run_validation(value)

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
            # A cleared color keeps its entry with a null token, so the key is required but a value
            # for it is not.
            ("null_color_token", [{"breakdownValue": "Chrome", "colorToken": None}]),
            # A breakdown value can legitimately be the empty string.
            ("blank_breakdown_value", [{"breakdownValue": "", "colorToken": "preset-1"}]),
            # A theme may carry more slots than the default palette, and the token wraps past its
            # end, so the pattern must not cap the index.
            ("color_token_past_the_default_palette", [{"breakdownValue": "Chrome", "colorToken": "preset-99"}]),
            (
                "null_breakdown_property",
                [{"breakdownValue": "Chrome", "colorToken": "preset-1", "breakdownProperty": None}],
            ),
            ("null_source", [{"breakdownValue": "Chrome", "colorToken": "preset-1", "source": None}]),
            # Clearing every color, and the nullable column's own value.
            ("empty_list", []),
            ("null", None),
        ]
    )
    def test_accepts(self, _name: str, value: object) -> None:
        for partial in (False, True):
            with self.subTest(partial=partial):
                assert self._field(partial=partial).run_validation(value) == value

    @parameterized.expand([("write", "run_validation"), ("read", "to_representation")])
    def test_keeps_a_key_the_child_serializer_does_not_declare_on(self, _name: str, method: str) -> None:
        # The child serializer rewrites an entry rather than describing it, so neither direction may
        # run entries through it. Without this, `somethingAddedLater` disappears and the entry gains
        # an explicit null `breakdownProperty`, which is data loss on a perfectly valid entry.
        #
        # Both directions matter because the dashboard saves the whole color list back, so a key
        # dropped on write is gone from a round trip even when the read preserves it.
        entries = [
            {
                "breakdownValue": "Chrome",
                "colorToken": "preset-1",
                "source": "manual",
                "somethingAddedLater": "kept",
            }
        ]

        assert getattr(self._field(partial=False), method)(entries) == entries
