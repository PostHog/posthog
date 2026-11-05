import json
from typing import Any

from parameterized import parameterized

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_bytecode
from posthog.temporal.ai_observability.run_trace_evaluation import build_trace_hog_globals

from products.ai_observability.backend.eval_suggestions import adapters


def _trace(events: list[tuple[str, dict[str, Any]]]) -> LLMTrace:
    return LLMTrace(
        id="trace-1",
        createdAt="2026-11-01T00:00:00Z",
        distinctId="user",
        events=[
            LLMTraceEvent(id=f"event-{index}", event=name, createdAt="2026-11-01T00:00:00Z", properties=properties)
            for index, (name, properties) in enumerate(events)
        ],
    )


def _verdict(check: adapters.AdaptedCheck, events: list[tuple[str, dict[str, Any]]]) -> bool | None:
    bytecode = adapters.compile_check(check)
    result = execute_hog_eval_bytecode(
        bytecode, build_trace_hog_globals(_trace(events), "trace-1", bytecode=bytecode), allows_na=True
    )
    assert result["error"] is None, result["error"]
    return result["verdict"]


def _answer(text: str, **properties: Any) -> tuple[str, dict[str, Any]]:
    return "$ai_generation", {"$ai_output_choices": [{"role": "assistant", "content": text}], **properties}


def _calls(*calls: tuple[str, dict[str, Any], str]) -> tuple[str, dict[str, Any]]:
    tool_calls = [
        {"type": "function", "id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}
        for name, arguments, call_id in calls
    ]
    return "$ai_generation", {"$ai_output_choices": [{"role": "assistant", "content": "", "tool_calls": tool_calls}]}


def _span(name: str, error: str | None = None) -> tuple[str, dict[str, Any]]:
    return "$ai_span", {"$ai_span_name": name, **({"$ai_is_error": True, "$ai_error": error} if error else {})}


UNRECOVERED = adapters.unrecovered_errors(["GraphInterrupt(value=1)", "Approval paused: waiting for a person"])
REPEATS = adapters.repeated_tool_calls(
    adapters.skipped_repeat_tools({"run_action": 90, "check_job_status": 5}, ["run_action"])
)


class TestAdaptedChecks:
    @parameterized.expand(
        [
            (
                "tool_fails_without_retry",
                UNRECOVERED,
                [_answer("hi"), _span("search", "Timeout"), _answer("done")],
                False,
            ),
            (
                "model_call_fails_last",
                UNRECOVERED,
                [_answer("x"), _answer("", **{"$ai_is_error": True, "$ai_error": "model not found"})],
                False,
            ),
            ("retry_recovers", UNRECOVERED, [_span("search", "Timeout"), _span("search"), _answer("done")], True),
            (
                "approval_pause_is_not_a_failure",
                UNRECOVERED,
                [_answer("hi"), _span("approval", "GraphInterrupt(value=2)")],
                True,
            ),
            (
                "team_pause_class_is_ignored",
                UNRECOVERED,
                [_span("gate", "Approval paused: waiting for a person")],
                True,
            ),
            ("identical_calls_repeat", REPEATS, [_calls(("search", {"q": "a"}, f"c{i}")) for i in range(3)], False),
            ("exploration_with_new_arguments", REPEATS, [_calls(("search", {"q": q}, q)) for q in "abc"], True),
            ("dispatcher_is_skipped", REPEATS, [_calls(("run_action", {"step": 1}, f"c{i}")) for i in range(5)], None),
            (
                "polling_tool_is_skipped",
                REPEATS,
                [_calls(("check_job_status", {"job": 1}, f"c{i}")) for i in range(4)],
                None,
            ),
            ("refusal_in_final_answer", adapters.refusals(), [_answer("I’m unable to share that.")], False),
            (
                "refusal_only_in_earlier_step",
                adapters.refusals(),
                [_answer("I can't help with that"), _answer("Here it is")],
                True,
            ),
            (
                "links_and_versions_are_not_sensitive",
                adapters.sensitive_data(),
                [_answer("See https://example.com/docs for v2.31.4")],
                True,
            ),
            ("email_in_final_answer", adapters.sensitive_data(), [_answer("Ask jane.doe@acme.io for access")], False),
            (
                "automated_and_placeholder_addresses",
                adapters.sensitive_data(),
                [_answer("Mail support@example.com or noreply@acme.io")],
                True,
            ),
            ("card_number", adapters.sensitive_data(), [_answer("Card 4242 4242 4242 4242 is on file")], False),
            ("secret_key", adapters.sensitive_data(), [_answer("Use sk-abcdefghijklmnopqrstuvwx123")], False),
            ("no_final_text_does_not_apply", adapters.sensitive_data(), [_span("search")], None),
        ]
    )
    def test_verdict(self, _name: str, check: adapters.AdaptedCheck, events: list, expected: bool | None) -> None:
        assert _verdict(check, events) is expected

    def test_cost_check_uses_the_team_limit(self) -> None:
        check = adapters.cost_latency(max_cost_usd=0.5, max_latency_seconds=30)
        expensive = _trace([_answer("x")])
        bytecode = adapters.compile_check(check)
        globals_dict = build_trace_hog_globals(
            expensive.model_copy(update={"totalCost": 0.9}), "trace-1", bytecode=bytecode
        )
        assert execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=True)["verdict"] is False
