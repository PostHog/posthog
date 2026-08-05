from django.test import SimpleTestCase

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
