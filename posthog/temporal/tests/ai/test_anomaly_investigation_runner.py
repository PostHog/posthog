from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.runner import (
    FINAL_REPORT_TOOL_NAME,
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


class _StubMessage:
    # Minimal stand-in for a LangChain AIMessage — the runner only reads .content and .tool_calls.
    def __init__(self, *, content: Any = "", tool_calls: list[dict] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


def _final_report_call(verdict: str) -> dict:
    return {
        "name": FINAL_REPORT_TOOL_NAME,
        "args": {
            "verdict": verdict,
            "summary": "Recovered after an explicit finalize nudge.",
            "hypotheses": [],
            "recommendations": [],
        },
    }


async def _run_with_scripted_llm(
    tool_turn_responses: list[_StubMessage],
    final_turn_responses: list[_StubMessage],
) -> tuple[Any, AsyncMock]:
    tools_runnable = MagicMock()
    tools_runnable.ainvoke = AsyncMock(side_effect=tool_turn_responses)
    final_runnable = MagicMock()
    final_runnable.ainvoke = AsyncMock(side_effect=final_turn_responses)

    llm = MagicMock()
    # bind_tools is called twice: first for the tool-calling loop, then for the finalize turn.
    llm.bind_tools.side_effect = [tools_runnable, final_runnable]

    with (
        patch("ee.hogai.llm.MaxChatAnthropic", return_value=llm),
        patch("posthog.temporal.ai.anomaly_investigation.runner._build_callbacks", return_value=[]),
    ):
        result = await run_investigation(
            team=MagicMock(id=1),
            user=MagicMock(id=1),
            anomaly_context="An hourly metric ticked up.",
        )
    return result, final_runnable.ainvoke


@pytest.mark.asyncio
async def test_run_investigation_nudges_for_report_when_model_stops_without_tool_call() -> None:
    # Sonnet 5 thinking-only turn: a thinking block, no text, no tool call — the empty-output
    # path that otherwise collapses to "Agent returned no final message". The finalize nudge
    # should elicit the report tool call and recover a real verdict.
    stop_turn = _StubMessage(content=[{"type": "thinking", "thinking": "the spike looks benign"}])
    recovered = _StubMessage(tool_calls=[_final_report_call("false_positive")])

    result, finalize_ainvoke = await _run_with_scripted_llm([stop_turn], [recovered])

    assert result.report.verdict == "false_positive"
    assert result.report.summary != "Agent returned no final message."
    finalize_ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_investigation_recovers_text_json_without_extra_finalize_call() -> None:
    # When the stop turn already carries the report as plain-text JSON, recover it in place —
    # no wasted second LLM round trip.
    report_json = '{"verdict":"inconclusive","summary":"Within normal variance.","hypotheses":[],"recommendations":[]}'
    result, finalize_ainvoke = await _run_with_scripted_llm([_StubMessage(content=report_json)], [])

    assert result.report.verdict == "inconclusive"
    assert result.report.summary == "Within normal variance."
    finalize_ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_investigation_falls_back_when_nudge_also_yields_no_report() -> None:
    # The nudge is best-effort: if the model still returns nothing usable, degrade to the
    # inconclusive fallback rather than looping or raising.
    result, _ = await _run_with_scripted_llm([_StubMessage(content="")], [_StubMessage(content="")])

    assert result.report.verdict == "inconclusive"
    assert result.report.summary == "Agent returned no final message."
