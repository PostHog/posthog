from typing import Any, Union
from unittest import TestCase

from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default


class TestMultiPropertyBreakdown(TestCase):
    """
    This helper function is tested implicitly via API tests
    but these edge cases were discovered during exploratory testing
    """

    def test_handles_empty_inputs(self):
        data = {}
        result: Union[list[list[dict[str, Any]]], list[dict[str, Any]]] = []

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            assert False, "should not raise any KeyError"

    def test_handles_empty_breakdowns_array(self):
        data = {"breakdowns": [], "insight": "FUNNELS", "breakdown_type": "event"}
        result: Union[list[list[dict[str, Any]]], list[dict[str, Any]]] = [{}]

        try:
            protect_old_clients_from_multi_property_default(data, result)
        except KeyError:
            assert False, "should not raise any KeyError"
