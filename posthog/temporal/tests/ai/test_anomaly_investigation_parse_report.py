import json
import logging

import pytest

from posthog.temporal.ai.anomaly_investigation.runner import PARSE_FAILURE_RAW_PREVIEW_CHARS, _parse_report

_VALID_REPORT = {
    "verdict": "true_positive",
    "summary": "Confirmed real shift in active orgs.",
    "hypotheses": [
        {
            "title": "Marketing campaign",
            "rationale": "Campaign launched at the start of the window.",
            "evidence": ["utm_source share grew 4x"],
        }
    ],
    "recommendations": ["Confirm with marketing team."],
}


def _as_json(payload: dict) -> str:
    return json.dumps(payload)


@pytest.mark.parametrize(
    "raw,expected_verdict,expected_summary_substr",
    [
        # Plain JSON.
        (_as_json(_VALID_REPORT), "true_positive", "Confirmed real shift"),
        # Leading + trailing prose around the JSON.
        (
            "Here's the report:\n" + _as_json(_VALID_REPORT) + "\n\nLet me know if you need more.",
            "true_positive",
            "Confirmed real shift",
        ),
        # Markdown ```json fence.
        ("```json\n" + _as_json(_VALID_REPORT) + "\n```", "true_positive", "Confirmed real shift"),
        # Bare ``` fence with no language tag.
        ("```\n" + _as_json(_VALID_REPORT) + "\n```", "true_positive", "Confirmed real shift"),
        # Uppercase JSON tag (some models capitalize).
        ("```JSON\n" + _as_json(_VALID_REPORT) + "\n```", "true_positive", "Confirmed real shift"),
        # A prose example fence followed by the real report fence — second fence wins.
        (
            'Example shape: ```json\n{"verdict": "?"}\n``` and the actual report:\n```json\n'
            + _as_json(_VALID_REPORT)
            + "\n```",
            "true_positive",
            "Confirmed real shift",
        ),
    ],
)
def test_parse_report_extracts_valid_json(raw, expected_verdict, expected_summary_substr) -> None:
    report = _parse_report(raw)
    assert report.verdict == expected_verdict
    assert expected_summary_substr in report.summary


def test_parse_report_accepts_langchain_content_blocks() -> None:
    content = [
        {"type": "text", "text": "Here you go:\n"},
        {"type": "text", "text": _as_json(_VALID_REPORT)},
    ]
    report = _parse_report(content)
    assert report.verdict == "true_positive"


def test_parse_report_returns_inconclusive_for_empty_final_message(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="posthog.temporal.ai.anomaly_investigation.runner"):
        report = _parse_report("", tool_calls_used=3)
    assert report.verdict == "inconclusive"
    assert "no final message" in report.summary
    # The empty-message branch should be tagged distinctly so we can alert on it separately from JSON failures.
    assert any(
        rec.message == "anomaly_investigation.parse_report_failed"
        and getattr(rec, "reason", None) == "empty_final_message"
        for rec in caplog.records
    )


def test_parse_report_logs_raw_content_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    raw = "I considered the metric and decided not to emit JSON, sorry."
    with caplog.at_level(logging.WARNING, logger="posthog.temporal.ai.anomaly_investigation.runner"):
        report = _parse_report(raw, tool_calls_used=2)
    assert report.verdict == "inconclusive"
    matching = [rec for rec in caplog.records if rec.message == "anomaly_investigation.parse_report_failed"]
    assert len(matching) == 1
    rec = matching[0]
    assert getattr(rec, "reason", None) == "no_valid_json_found"
    assert getattr(rec, "tool_calls_used", None) == 2
    assert getattr(rec, "raw_content_length", None) == len(raw)
    assert getattr(rec, "raw_content_preview", None) == raw


def test_parse_report_truncates_raw_preview_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    raw = "x" * (PARSE_FAILURE_RAW_PREVIEW_CHARS + 500)
    with caplog.at_level(logging.WARNING, logger="posthog.temporal.ai.anomaly_investigation.runner"):
        _parse_report(raw)
    matching = [rec for rec in caplog.records if rec.message == "anomaly_investigation.parse_report_failed"]
    assert len(matching) == 1
    rec = matching[0]
    preview = getattr(rec, "raw_content_preview", None)
    assert preview is not None
    assert len(preview) == PARSE_FAILURE_RAW_PREVIEW_CHARS
    assert getattr(rec, "raw_content_length", None) == len(raw)


def test_parse_report_logs_schema_errors_when_json_parses_but_fails_validation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Valid JSON, but `verdict` is not one of the allowed literals — schema fails.
    raw = '{"verdict": "maybe", "summary": "Could go either way."}'
    with caplog.at_level(logging.WARNING, logger="posthog.temporal.ai.anomaly_investigation.runner"):
        report = _parse_report(raw)
    assert report.verdict == "inconclusive"
    rec = next(rec for rec in caplog.records if rec.message == "anomaly_investigation.parse_report_failed")
    parse_errors = getattr(rec, "parse_errors", None) or []
    assert any("schema:" in entry and "verdict" in entry for entry in parse_errors)
