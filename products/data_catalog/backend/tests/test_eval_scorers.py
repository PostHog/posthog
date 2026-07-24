from typing import Any

from parameterized import parameterized

from products.data_catalog.evals.scorers import _search_surfaced_metrics
from products.posthog_ai.eval_harness.log_parser import ToolCall

_METRIC_OUTPUT = '{"matches":[],"governed_metrics":[{"name":"monthly_recurring_revenue"}],"hint":"run it"}'


def _tool_call(**overrides: Any) -> ToolCall:
    defaults: dict[str, Any] = {
        "name": "search",
        "input": {},
        "output": "",
        "is_error": False,
        "call_id": "call-1",
        "position": 0,
        "raw_name": "exec",
        "is_exec_unwrapped": True,
    }
    defaults.update(overrides)
    return ToolCall(**defaults)


class TestSearchSurfacedMetrics:
    @parameterized.expand(
        [
            ("unwrapped_search_with_metrics", _tool_call(name="search", output=_METRIC_OUTPUT), True),
            (
                "wrapped_exec_search_with_metrics",
                _tool_call(name="exec", input={"command": "search revenue"}, output=_METRIC_OUTPUT),
                True,
            ),
            ("malformed_json_substring_fallback", _tool_call(output='garbage "governed_metrics": [x]'), True),
            ("search_without_metrics", _tool_call(name="search", output='{"matches":["x"]}'), False),
            ("errored_search", _tool_call(name="search", output=_METRIC_OUTPUT, is_error=True), False),
            ("non_search_command", _tool_call(name="info", output=_METRIC_OUTPUT), False),
        ]
    )
    def test_detects_search_that_surfaced_governed_metrics(self, _name: str, call: ToolCall, expected: bool) -> None:
        assert _search_surfaced_metrics(call) is expected
