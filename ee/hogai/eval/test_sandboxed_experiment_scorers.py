"""Unit tests for the grading logic the metric-schema-discovery eval uses.

Exercises ``FirstUpdateMetricShape`` and the metric-shape validators from
``sandboxed/experiments/scorers.py`` directly, lightweight as it's given
hand-built metric dicts and synthetic ACP log lines, no sandboxed stack.

Lives one level above ``sandboxed/`` on purpose: a test under that package
inherits its ``conftest.py``, whose autouse fixtures boot the full eval harness
(Temporal, MCP, gateway, Django). Up here it stays a fast unit test.
"""

from __future__ import annotations

import json

import pytest

from braintrust import Score

from ee.hogai.eval.sandboxed.experiments.scorers import (
    FirstUpdateMetricShape,
    validate_ratio_revenue_metric,
    validate_retention_metric,
)


def _ratio(numerator: dict, denominator: dict | None = None) -> dict:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "ratio",
        "numerator": numerator,
        "denominator": denominator or {"kind": "EventsNode", "event": "$pageview"},
    }


def _retention(**overrides) -> dict:
    metric = {
        "kind": "ExperimentMetric",
        "metric_type": "retention",
        "start_event": {"kind": "EventsNode", "event": "$pageview"},
        "completion_event": {"kind": "EventsNode", "event": "uploaded_file"},
        "retention_window_start": 0,
        "retention_window_end": 7,
        "retention_window_unit": "day",
        "start_handling": "first_seen",
    }
    metric.update(overrides)
    return metric


RATIO_SUM = _ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum", "math_property": "revenue"})
RATIO_IS_SET = _ratio(
    {
        "kind": "EventsNode",
        "event": "purchase_completed",
        "properties": [{"key": "revenue", "value": "is_set", "operator": "is_set", "type": "event"}],
    }
)


@pytest.mark.parametrize(
    "metrics,expected_pass",
    [
        ([RATIO_SUM], True),
        ([{"metric_type": "mean", "source": {}}, RATIO_SUM], True),  # ratio found alongside other metrics
        ([RATIO_IS_SET], False),  # is_set filter does not aggregate
        ([_ratio({"kind": "EventsNode", "event": "purchase_completed", "math_property": "revenue"})], False),  # no math
        ([_ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum"})], False),  # no math_property
        (
            [_ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum", "math_property": "amount"})],
            False,
        ),
        ([{"metric_type": "mean", "source": {}}], False),  # no ratio metric present
    ],
    ids=["sum", "sum-among-others", "is-set", "missing-math", "missing-math-property", "wrong-property", "no-ratio"],
)
def test_validate_ratio_revenue_metric(metrics: list[dict], expected_pass: bool) -> None:
    passed, reason = validate_ratio_revenue_metric(metrics)
    assert passed is expected_pass
    assert isinstance(reason, str) and reason


@pytest.mark.parametrize(
    "metrics,expected_pass",
    [
        ([_retention()], True),
        ([{"metric_type": "ratio"}, _retention()], True),
        ([_retention(retention_window_start=None)], True),  # required key present even if value is None
        ([{k: v for k, v in _retention().items() if k not in ("retention_window_start", "start_handling")}], False),
        ([{k: v for k, v in _retention().items() if k != "start_handling"}], False),  # missing a required field
        ([{k: v for k, v in _retention().items() if k != "retention_window_start"}], False),
        ([{"metric_type": "ratio"}], False),  # no retention metric present
    ],
    ids=[
        "full",
        "among-others",
        "present-none",
        "missing-both",
        "missing-start-handling",
        "missing-window-start",
        "no-retention",
    ],
)
def test_validate_retention_metric(metrics: list[dict], expected_pass: bool) -> None:
    passed, reason = validate_retention_metric(metrics)
    assert passed is expected_pass
    assert isinstance(reason, str) and reason


def _acp_line(update: dict) -> str:
    return json.dumps(
        {
            "notification": {"method": "session/update", "params": {"update": update}},
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )


def _tool_call(call_id: str, tool_name: str, raw_input: dict, *, is_error: bool = False) -> list[str]:
    """Emit the tool_call + completing tool_call_update pair for one tool invocation."""
    return [
        _acp_line(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "_meta": {"claudeCode": {"toolName": tool_name}},
                "rawInput": raw_input,
            }
        ),
        _acp_line(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": "failed" if is_error else "completed",
                "rawOutput": "error" if is_error else "ok",
            }
        ),
    ]


def _output(*tool_calls: list[str]) -> dict:
    lines: list[str] = []
    for call in tool_calls:
        lines.extend(call)
    return {"raw_log": "\n".join(lines), "prompt": "add a metric"}


def _score(output: dict | None, validator=validate_ratio_revenue_metric) -> Score:
    return FirstUpdateMetricShape()._run_eval_sync(output, expected={"first_update_metric_shape": validator})


def test_first_update_skipped_when_validator_absent() -> None:
    score = FirstUpdateMetricShape()._run_eval_sync(_output(), expected={})
    assert score.score == 1.0
    assert score.metadata.get("skipped") is True


def test_first_update_no_output() -> None:
    assert _score(None).score == 0.0


def test_first_update_never_called() -> None:
    score = _score(_output(_tool_call("c1", "experiment-get", {})))
    assert score.score == 0.0
    assert "never called" in score.metadata["reason"]


def test_first_update_correct_first_try() -> None:
    score = _score(_output(_tool_call("c1", "mcp__posthog__experiment-update", {"metrics": [RATIO_SUM]})))
    assert score.score == 1.0
    assert score.metadata["call_count"] == 1


def test_first_update_only_first_call_counts() -> None:
    # Wrong on the first call, recovered on the second — the first-try methodology must still fail it.
    score = _score(
        _output(
            _tool_call("c1", "experiment-update", {"metrics": [RATIO_IS_SET]}, is_error=True),
            _tool_call("c2", "experiment-update", {"metrics": [RATIO_SUM]}),
        )
    )
    assert score.score == 0.0
    assert score.metadata["call_count"] == 2
    assert score.metadata["first_call_is_error"] is True


def test_first_update_error_call_still_graded_on_shape() -> None:
    # A correctly shaped payload that the API rejected for other reasons still counts as right shape.
    score = _score(_output(_tool_call("c1", "experiment-update", {"metrics": [RATIO_SUM]}, is_error=True)))
    assert score.score == 1.0


def test_first_update_reads_metrics_secondary() -> None:
    score = _score(_output(_tool_call("c1", "experiment-update", {"metrics_secondary": [RATIO_SUM]})))
    assert score.score == 1.0


def test_first_update_no_metrics_array() -> None:
    score = _score(_output(_tool_call("c1", "experiment-update", {"name": "renamed"})))
    assert score.score == 0.0
    assert "no metrics array" in score.metadata["reason"]
