from posthog.temporal.ai.anomaly_investigation.runner import (
    FINAL_REPORT_TOOL_NAME,
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
