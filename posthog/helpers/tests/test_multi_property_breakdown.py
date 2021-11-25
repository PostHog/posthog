from typing import Any, Dict, List, Union
from unittest import TestCase

from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default


class TestMultiPropertyBreakdown(TestCase):
    """
    This helper function is tested implicitly via API tests
    but these edge cases were discovered during exploratory testing
    """

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
