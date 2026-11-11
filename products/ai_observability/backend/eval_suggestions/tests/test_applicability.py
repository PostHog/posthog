from dataclasses import replace

from parameterized import parameterized

from posthog.schema import LLMTrace, LLMTraceEvent

from products.ai_observability.backend.eval_suggestions.applicability import (
    ContentProfile,
    applicable,
    trace_dispatcher_tools,
)
from products.ai_observability.backend.eval_suggestions.measure import SampledTrace
from products.ai_observability.backend.eval_suggestions.profile import TeamProfile

PROFILE = TeamProfile(
    sessions=0,
    session_traces=0,
    generations=1000,
    traces=200,
    generations_by_days_ago={0: 500, 1: 500},
    traces_by_days_ago={0: 100, 1: 100},
    tool_call_share=0.5,
    tool_counts={"run_action": 900, "search": 100},
    dispatcher_tools=(),
    session_share=0.9,
    mean_input_tokens=800.0,
    models=(),
    error_prefixes=(),
    segments={},
)
CONTENT = ContentProfile(
    traces=100,
    text_share=0.9,
    multi_turn_share=0.4,
    spanning_days_share=0.0,
    dispatcher_tools=(),
)


class TestApplicability:
    @parameterized.expand(
        [
            (
                "agent",
                PROFILE,
                CONTENT,
                ["unrecovered_errors", "repeated_tool_calls", "refusals", "sensitive_data"],
                ["user_correction", "sentiment", "prompt_injection"],
                "session",
            ),
            (
                "few_tool_calls",
                replace(PROFILE, tool_call_share=0.05),
                CONTENT,
                ["unrecovered_errors", "refusals", "sensitive_data"],
                ["user_correction", "sentiment", "prompt_injection"],
                "session",
            ),
            (
                "single_turn",
                PROFILE,
                replace(CONTENT, multi_turn_share=0.05),
                ["unrecovered_errors", "repeated_tool_calls", "refusals", "sensitive_data"],
                ["prompt_injection"],
                "trace",
            ),
            (
                "no_content",
                PROFILE,
                replace(CONTENT, text_share=0.1),
                ["unrecovered_errors", "repeated_tool_calls"],
                [],
                "session",
            ),
        ]
    )
    def test_rules(
        self,
        _name: str,
        profile: TeamProfile,
        content: ContentProfile,
        checks: list[str],
        judges: list[str],
        target: str,
    ) -> None:
        result = applicable(profile, content)
        assert [check.key for check in result.checks] == checks
        assert result.screened_judges == judges
        assert result.judge_target == target


def _trace_calling(trace_id: str, *tools: str) -> SampledTrace:
    events = [
        LLMTraceEvent(
            id=f"{trace_id}-{i}",
            event="$ai_generation",
            createdAt="2026-11-01T00:00:00Z",
            properties={"$ai_tools_called": tool},
        )
        for i, tool in enumerate(tools)
    ]
    return SampledTrace(
        trace=LLMTrace(id=trace_id, createdAt="2026-11-01T00:00:00Z", distinctId="user", events=events),
        held_out=False,
        spans_days=False,
        segments={},
        segment_values={},
        raw_segment_values={},
        final_text="",
        turn_text="",
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )


def test_dispatcher_is_the_tool_repeated_through_each_trace() -> None:
    traces = [_trace_calling(f"agent-{i}", *(["run_action"] * 6 + ["search"])) for i in range(6)]
    traces += [_trace_calling(f"lookup-{i}", "fetch_issue") for i in range(6)]
    assert trace_dispatcher_tools(traces) == ("run_action",)
