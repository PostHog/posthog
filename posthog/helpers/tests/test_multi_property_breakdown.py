from typing import Any, Dict, List
from unittest import TestCase

from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default


class TestMultiPropertyBreakdown(TestCase):
    def test_handles_empty_inputs(self):
        data: Dict[str, Any] = {}
        result: List = []

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            assert False, "should not raise any KeyError"

    def test_handles_empty_breakdowns_array(self):
        data: Dict[str, Any] = {"breakdowns": [], "insight": "FUNNELS", "breakdown_type": "event"}
        result: List = []

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            assert False, "should not raise any KeyError"

    def test_keeps_multi_property_breakdown_for_multi_property_requests(self):
        data: Dict[str, Any] = {"breakdowns": ["a", "b"], "insight": "FUNNELS", "breakdown_type": "event"}
        result: List[List[Dict[str, Any]]] = [[{"breakdown": ["a1", "b1"], "breakdown_value": ["a1", "b1"]}]]

        actual = protect_old_clients_from_multi_property_default(data, result)
        assert actual[0][0]["breakdowns"] == ["a1", "b1"]
        assert "breakdown" not in actual[0][0]

    def test_flattens_multi_property_breakdown_for_single_property_requests(self):
        data: Dict[str, Any] = {"breakdown": "a", "insight": "FUNNELS", "breakdown_type": "event"}
        result: List[List[Dict[str, Any]]] = [[{"breakdown": ["a1"], "breakdown_value": ["a1", "b1"]}]]

        actual = protect_old_clients_from_multi_property_default(data, result)
        assert actual[0][0]["breakdown"] == "a1"
        assert "breakdowns" not in actual[0][0]
