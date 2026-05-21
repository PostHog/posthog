"""Tests for the alert investigation prompt builders.

Covers the mode-aware system prompt selection plus the threshold context builder,
which is the new piece needed for threshold alerts to opt into the investigation
agent. The anomaly context builder is exercised indirectly by the workflow tests.
"""

from posthog.temporal.ai.anomaly_investigation.prompts import (
    ANOMALY_SYSTEM_PROMPT,
    THRESHOLD_SYSTEM_PROMPT,
    build_threshold_context,
    system_prompt_for_alert,
)


class TestSystemPromptForAlert:
    def test_picks_anomaly_prompt_for_detector_based_alerts(self) -> None:
        assert system_prompt_for_alert(has_detector_config=True) is ANOMALY_SYSTEM_PROMPT

    def test_picks_threshold_prompt_for_threshold_alerts(self) -> None:
        assert system_prompt_for_alert(has_detector_config=False) is THRESHOLD_SYSTEM_PROMPT

    def test_anomaly_prompt_mentions_simulate_detector(self) -> None:
        # Anomaly mode has the detector simulation tool exposed.
        assert "simulate_detector" in ANOMALY_SYSTEM_PROMPT

    def test_threshold_prompt_does_not_promise_simulate_detector(self) -> None:
        # Threshold mode does NOT expose simulate_detector — make sure the prompt
        # doesn't tell the agent to use a tool it doesn't have.
        assert "simulate_detector" not in THRESHOLD_SYSTEM_PROMPT


class TestBuildThresholdContext:
    def test_includes_bounds_and_calculated_value(self) -> None:
        ctx = build_threshold_context(
            alert_name="signups too low",
            metric_description="daily signups",
            condition_type="absolute_value",
            threshold_bounds={"lower": 10, "upper": None},
            threshold_kind="absolute",
            calculated_value=4.0,
            interval="day",
        )
        assert "signups too low" in ctx
        assert "daily signups" in ctx
        assert "lower=10" in ctx
        assert "upper" not in ctx.split("Threshold bounds:")[1].splitlines()[0]
        assert "4.0" in ctx

    def test_handles_no_bounds_gracefully(self) -> None:
        ctx = build_threshold_context(
            alert_name="alert",
            metric_description="metric",
            condition_type=None,
            threshold_bounds=None,
            threshold_kind=None,
            calculated_value=None,
            interval=None,
        )
        # No crash on missing fields, and the bounds line is explicit about it.
        assert "Threshold bounds: none" in ctx

    def test_includes_triggered_metadata_when_present(self) -> None:
        ctx = build_threshold_context(
            alert_name="alert",
            metric_description="metric",
            condition_type="absolute_value",
            threshold_bounds={"upper": 100},
            threshold_kind="absolute",
            calculated_value=150.0,
            interval="day",
            triggered_metadata={"series_index": 0, "breakdown_value": "us"},
        )
        assert "series_index=0" in ctx
        assert "breakdown_value=us" in ctx
