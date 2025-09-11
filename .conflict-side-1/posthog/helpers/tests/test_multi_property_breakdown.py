from typing import Any

from unittest import TestCase

from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default


class TestMultiPropertyBreakdown(TestCase):
    def test_handles_empty_inputs(self):
        data: dict[str, Any] = {}
        result: list = []

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            raise AssertionError("should not raise any KeyError")

    def test_handles_empty_breakdowns_array(self):
        data: dict[str, Any] = {
            "breakdowns": [],
            "insight": "FUNNELS",
            "breakdown_type": "event",
        }
        result: list = []

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            raise AssertionError("should not raise any KeyError")

    def test_keeps_multi_property_breakdown_for_multi_property_requests(self):
        data: dict[str, Any] = {
            "breakdowns": ["a", "b"],
            "insight": "FUNNELS",
            "breakdown_type": "event",
        }
        result: list[list[dict[str, Any]]] = [[{"breakdown": ["a1", "b1"], "breakdown_value": ["a1", "b1"]}]]

        actual = protect_old_clients_from_multi_property_default(data, result)

        # to satisfy mypy
        assert isinstance(actual, list)
        series = actual[0]
        assert isinstance(series, list)
        data = series[0]
        assert data["breakdowns"] == ["a1", "b1"]
        assert "breakdown" not in data

    def test_flattens_multi_property_breakdown_for_single_property_requests(self):
        data: dict[str, Any] = {
            "breakdown": "a",
            "insight": "FUNNELS",
            "breakdown_type": "event",
        }
        result: list[list[dict[str, Any]]] = [[{"breakdown": ["a1"], "breakdown_value": ["a1", "b1"]}]]

        actual = protect_old_clients_from_multi_property_default(data, result)

        # to satisfy mypy
        assert isinstance(actual, list)
        series = actual[0]
        assert isinstance(series, list)
        data = series[0]
        assert data["breakdown"] == "a1"
        assert "breakdowns" not in data
