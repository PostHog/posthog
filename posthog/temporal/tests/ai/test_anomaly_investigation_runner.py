import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.report import salvage_report
from posthog.temporal.ai.anomaly_investigation.runner import (
    FINAL_REPORT_TOOL_NAME,
    MAX_TOOL_CALLS,
    _build_callbacks,
    _parse_report,
    _report_from_tool_calls,
    run_investigation,
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


@parameterized.expand(
    [
        # Sonnet 5 leaks its text-tool-call syntax and stringifies the whole list — the exact
        # shape seen in production traces that collapsed to "Agent returned no final message".
        (
            "hypotheses_leaked_tag_string",
            '\n<parameter name="hypothesis">[{"title": "Real step-change", "rationale": "Sustained climb.", "evidence": ["Rose 10 -> 60/hr"]}]',
            ["Aggregate to daily buckets."],
        ),
        # Plain JSON array in a string, no leaked tag.
        (
            "hypotheses_plain_json_string",
            '[{"title": "Bot spike", "rationale": "Traffic surge.", "evidence": []}]',
            ["Filter bots."],
        ),
    ]
)
def test_report_from_tool_calls_recovers_stringified_hypotheses(
    _name: str, hypotheses: str, recommendations: list[str]
) -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "true_positive",
                    "summary": "A genuine sustained shift.",
                    "hypotheses": hypotheses,
                    "recommendations": recommendations,
                },
            }
        ]
    )

    assert report is not None
    assert report.hypotheses[0].title in ("Real step-change", "Bot spike")
    assert report.recommendations == recommendations


def test_report_from_tool_calls_recovers_stringified_recommendations() -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "inconclusive",
                    "summary": "Unclear.",
                    "hypotheses": [],
                    "recommendations": '<parameter name="recommendation">["Check the dashboard.", "Ask the owning team."]',
                },
            }
        ]
    )

    assert report is not None
    assert report.recommendations == ["Check the dashboard.", "Ask the owning team."]


def test_report_from_tool_calls_preserves_markup_inside_recovered_content() -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "inconclusive",
                    "summary": "x",
                    "hypotheses": [],
                    "recommendations": '<parameter name="recommendation">["Audit the <parameter name=foo> leak in the logs."]',
                },
            }
        ]
    )

    assert report is not None
    assert report.recommendations == ["Audit the <parameter name=foo> leak in the logs."]


@parameterized.expand(
    [
        ("empty", ""),
        ("whitespace", "   "),
        ("tag_only", '<parameter name="hypothesis">'),
        ("prose_no_array", "the metric doubled overnight"),
    ]
)
def test_report_from_tool_calls_rejects_unrecoverable_stringified_hypotheses(_name: str, hypotheses: str) -> None:
    report = _report_from_tool_calls(
        [
            {
                "name": FINAL_REPORT_TOOL_NAME,
                "args": {
                    "verdict": "true_positive",
                    "summary": "x",
                    "hypotheses": hypotheses,
                    "recommendations": [],
                },
            }
        ]
    )

    assert report is None


@parameterized.expand(
    [
        # Hypothesis fields flattened to the top level, with the evidence array leaked as
        # a tagged string under `hypotheses` (trace shape from 2026-07-27).
        (
            "flattened_hypothesis_with_leaked_evidence_tag",
            {
                "verdict": "true_positive",
                "summary": "s",
                "title": "Single account driving skips",
                "rationale": "One tenant loops on the cap check.",
                "hypotheses": '\n<parameter name="evidence">["88% of events from one distinct_id."]',
            },
            [("Single account driving skips", ["88% of events from one distinct_id."])],
            [],
        ),
        # The recommendations parameter concatenated into the hypotheses string value.
        (
            "sibling_recommendations_concatenated_into_hypotheses_string",
            {
                "verdict": "true_positive",
                "summary": "s",
                "hypotheses": '[{"title": "Bulk sync", "rationale": "Batch job.", "evidence": ["0 -> 54 in one bucket."]}], "recommendations": ["Check the connector."]',
            },
            [("Bulk sync", ["0 -> 54 in one bucket."])],
            ["Check the connector."],
        ),
        # Leaked tag plus an array cut off before its closing bracket.
        (
            "truncated_hypotheses_array_missing_closing_bracket",
            {
                "verdict": "true_positive",
                "summary": "s",
                "hypotheses": '\n<parameter name="hypotheses">[{"title": "Batch eval run", "rationale": "Tight burst.", "evidence": ["7x hourly baseline."]}',
                "recommendations": ["Confirm the eval job."],
            },
            [("Batch eval run", ["7x hourly baseline."])],
            ["Confirm the eval job."],
        ),
    ]
)
def test_report_from_tool_calls_recovers_production_manglings(
    _name: str,
    args: dict,
    expected_hypotheses: list[tuple[str, list[str]]],
    expected_recommendations: list[str],
) -> None:
    report = _report_from_tool_calls([{"name": FINAL_REPORT_TOOL_NAME, "args": args}])

    assert report is not None
    assert report.verdict == "true_positive"
    assert [(hypothesis.title, hypothesis.evidence) for hypothesis in report.hypotheses] == expected_hypotheses
    assert report.recommendations == expected_recommendations


def test_salvage_report_keeps_verdict_and_summary_when_hypotheses_unrecoverable() -> None:
    report = salvage_report(
        {
            "verdict": "true_positive",
            "summary": "One tenant drove the spike.",
            "hypotheses": "prose with no recoverable array",
            "recommendations": ["Check the tenant."],
        }
    )

    assert report is not None
    assert report.verdict == "true_positive"
    assert report.summary == "One tenant drove the spike."
    assert report.hypotheses == []
    assert report.recommendations == ["Check the tenant."]


@parameterized.expand(
    [
        ("invalid_verdict", {"verdict": "maybe", "summary": "x"}),
        # A blank summary must not gate notifications: a salvaged false_positive with no
        # explanation would silently suppress the alert.
        ("blank_summary", {"verdict": "false_positive", "summary": "   ", "hypotheses": "prose"}),
    ]
)
def test_salvage_report_rejects_untrustworthy_args(_name: str, args: dict) -> None:
    assert salvage_report(args) is None


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


class _ScriptedRunnable:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)

    async def ainvoke(self, messages, config=None):
        return self._responses.pop(0)


def _budget_burning_turn() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "noop_tool", "args": {}, "id": f"call-{i}"} for i in range(MAX_TOOL_CALLS)],
    )


def _report_turn(args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": FINAL_REPORT_TOOL_NAME, "args": args, "id": "report-1"}])


_UNRECOVERABLE_REPORT_ARGS = {
    "verdict": "true_positive",
    "summary": "One tenant drove the spike.",
    "hypotheses": "prose with no recoverable array",
    "recommendations": ["Check the tenant."],
}
_VALID_REPORT_ARGS = {
    "verdict": "true_positive",
    "summary": "One tenant drove the spike.",
    "hypotheses": [{"title": "Runaway tenant", "rationale": "Loops on the cap check.", "evidence": []}],
    "recommendations": ["Check the tenant."],
}


@pytest.mark.parametrize(
    "finalize_responses,expected_hypothesis_count",
    [
        pytest.param(
            [_report_turn(_UNRECOVERABLE_REPORT_ARGS), _report_turn(_VALID_REPORT_ARGS)],
            1,
            id="retry_recovers_full_report",
        ),
        pytest.param(
            [_report_turn(_UNRECOVERABLE_REPORT_ARGS), _report_turn(_UNRECOVERABLE_REPORT_ARGS)],
            0,
            id="salvage_after_failed_retry",
        ),
        pytest.param(
            [_report_turn(_UNRECOVERABLE_REPORT_ARGS), _report_turn({"verdict": "maybe", "summary": "x"})],
            0,
            id="salvage_first_attempt_when_retry_comes_back_worse",
        ),
    ],
)
async def test_finalize_turn_retries_then_salvages_invalid_report(
    finalize_responses: list, expected_hypothesis_count: int
) -> None:
    llm = MagicMock()
    llm.bind_tools.side_effect = lambda tools: (
        _ScriptedRunnable([_budget_burning_turn()]) if len(tools) > 1 else _ScriptedRunnable(finalize_responses)
    )

    with (
        patch("ee.hogai.llm.MaxChatAnthropic", return_value=llm),
        patch("posthog.temporal.ai.anomaly_investigation.runner.posthoganalytics") as mock_module,
    ):
        mock_module.default_client = None
        result = await run_investigation(
            team=MagicMock(id=1),
            user=MagicMock(id=2),
            anomaly_context="anomaly context",
            alert=None,
        )

    assert result.tool_calls_used == MAX_TOOL_CALLS
    assert result.report.verdict == "true_positive"
    assert result.report.summary == "One tenant drove the spike."
    assert len(result.report.hypotheses) == expected_hypothesis_count
    assert result.report.recommendations == ["Check the tenant."]
