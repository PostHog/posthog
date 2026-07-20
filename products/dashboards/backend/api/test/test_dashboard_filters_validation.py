from django.test import SimpleTestCase

from products.dashboards.backend.api.dashboard import DashboardSerializer


class TestDashboardFiltersValidation(SimpleTestCase):
    def _validate(self, value):
        # `validate_filters` is a DRF field validator, callable directly without a request or DB.
        return DashboardSerializer().validate_filters(value)

    def test_rejects_non_dict(self):
        import rest_framework.serializers as serializers

        try:
            self._validate(["not", "a", "dict"])
        except serializers.ValidationError:
            return
        raise AssertionError("expected ValidationError")

    def test_rejects_non_list_non_group_properties(self):
        import rest_framework.serializers as serializers

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

    def test_passes_flat_list_properties_through(self):
        prop = {"key": "$browser", "value": "Chrome", "type": "event"}
        result = self._validate({"properties": [prop]})
        assert result["properties"] == [prop]

    def test_drops_empty_property_group(self):
        result = self._validate({"date_from": "-7d", "properties": {"type": "AND", "values": []}})
        assert "properties" not in result
        assert result["date_from"] == "-7d"

    def test_passes_missing_properties_through(self):
        assert self._validate({"date_from": "-7d"}) == {"date_from": "-7d"}
