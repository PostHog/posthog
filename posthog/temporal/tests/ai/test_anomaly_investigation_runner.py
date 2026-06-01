import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ai.anomaly_investigation.runner import (
    FINAL_REPORT_TOOL_NAME,
    _build_callbacks,
    _parse_report,
    _report_from_tool_calls,
)


def test_report_from_tool_calls_accepts_structured_final_report() -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "false_positive",
                    "summary": "The spike is within normal low-volume variance.",
                    "hypotheses": [
                        {
                            "title": "Low-volume noise",
                            "rationale": "The metric has sparse hourly counts.",
                            "evidence": ["The triggered bucket was close to recent peaks."],
                        }
                    ],
                    "recommendations": ["Aggregate to daily buckets."],
                },
            }
        ]
    )

    assert report is not None
    assert report.verdict == "false_positive"
    assert report.summary == "The spike is within normal low-volume variance."
    assert report.hypotheses[0].title == "Low-volume noise"
    assert report.recommendations == ["Aggregate to daily buckets."]


def test_report_from_tool_calls_ignores_invalid_structured_final_report() -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "maybe",
                    "summary": "Invalid verdict.",
                },
            }
        ]
    )

    assert report is None


def test_parse_report_keeps_plain_json_fallback() -> None:
    report = _parse_report(
        '{"verdict":"inconclusive","summary":"Need manual review.","hypotheses":[],"recommendations":[]}'
    )

    assert report.verdict == "inconclusive"
    assert report.summary == "Need manual review."


@pytest.mark.parametrize(
    "alert_id,expected_properties",
    [
        pytest.param(
            "alert-uuid",
            {"ai_product": "alert_investigation_agent", "team_id": 314, "alert_id": "alert-uuid"},
            id="with_alert",
        ),
        pytest.param(
            None,
            {"ai_product": "alert_investigation_agent", "team_id": 314},
            id="without_alert",
        ),
    ],
)
def test_build_callbacks_tags_ai_product_for_llm_analytics(alert_id, expected_properties) -> None:
    team = MagicMock(id=314)
    alert = MagicMock(id=alert_id) if alert_id is not None else None
    sentinel_client = MagicMock(name="default_client")

    with (
        patch("posthog.temporal.ai.anomaly_investigation.runner.posthoganalytics") as mock_module,
        patch("posthog.temporal.ai.anomaly_investigation.runner.CallbackHandler") as mock_handler,
    ):
        mock_module.default_client = sentinel_client

        callbacks = _build_callbacks(team=team, alert=alert)

    assert callbacks == [mock_handler.return_value]
    mock_handler.assert_called_once()
    args, kwargs = mock_handler.call_args
    assert args[0] is sentinel_client
    assert kwargs["distinct_id"] == "314"
    assert kwargs["trace_id"].startswith("alert-investigation-")
    assert kwargs["properties"] == expected_properties


def test_build_callbacks_skips_when_default_client_missing() -> None:
    team = MagicMock(id=1)

    with patch("posthog.temporal.ai.anomaly_investigation.runner.posthoganalytics") as mock_module:
        mock_module.default_client = None
        callbacks = _build_callbacks(team=team, alert=None)

    assert callbacks == []
