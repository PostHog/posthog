import json
from typing import Any

from parameterized import parameterized

from posthog.schema import LLMTrace, LLMTraceEvent

from products.ai_observability.backend.logic.eval_suggestions import adapters
from products.ai_observability.backend.logic.evaluations.hog_runtime import (
    build_trace_hog_globals,
    execute_hog_eval_bytecode,
)


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


def _otel_call(name: str, arguments: dict[str, Any], call_id: str) -> tuple[str, dict[str, Any]]:
    part = {"type": "tool_call", "name": name, "arguments": arguments, "id": call_id}
    return "$ai_generation", {"$ai_output_choices": [{"role": "assistant", "parts": [part]}]}


def _span(name: str, error: str | None = None) -> tuple[str, dict[str, Any]]:
    return "$ai_span", {"$ai_span_name": name, **({"$ai_is_error": True, "$ai_error": error} if error else {})}


UNRECOVERED = adapters.unrecovered_errors(
    [
        "GraphInterrupt(value=1)",
        "Approval paused: waiting for a person",
        "('Connection aborted.', RemoteDisconnected('Remote end closed connection'))",
        "ApprovalServiceError: 503 Service Unavailable",
    ]
)
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
            # Mentioning an abort or an approval does not make a real failure a pause.
            ("connection_abort_is_a_failure", UNRECOVERED, [_span("search", "('Connection aborted.', x)")], False),
            (
                "approval_service_outage_is_a_failure",
                UNRECOVERED,
                [_span("approve", "ApprovalServiceError: 503")],
                False,
            ),
            # Some SDKs send the message without the flag.
            (
                "error_message_without_the_flag",
                UNRECOVERED,
                [("$ai_span", {"$ai_span_name": "search", "$ai_error": "Timeout"})],
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
                "refusal_word_inside_another_word",
                adapters.refusals(),
                [_answer("The API can't help here, so I used the CLI.")],
                True,
            ),
            (
                "unable_to_find_is_not_a_refusal",
                adapters.refusals(),
                [_answer("I'm unable to find any bug; it is correct.")],
                True,
            ),
            ("decline", adapters.refusals(), [_answer("I must decline this request.")], False),
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
            (
                "sk_inside_a_path_is_not_a_key",
                adapters.sensitive_data(),
                [_answer("Read /docs/ask-questions-about-your-data first")],
                True,
            ),
            (
                "sk_inside_a_word_is_not_a_key",
                adapters.sensitive_data(),
                [_answer("See our risk-management-frameworks guide")],
                True,
            ),
            ("no_final_text_does_not_apply", adapters.sensitive_data(), [_span("search")], None),
            # The email went to a tool, and the answer the user read has none.
            (
                "email_only_in_a_tool_call",
                adapters.sensitive_data(),
                [_answer("I'll send the invite."), _calls(("send_invite", {"email": "jane.doe@acme.io"}, "c1"))],
                True,
            ),
            # OpenAI-compatible clients send an empty tool_calls list on a plain answer.
            (
                "email_in_an_answer_with_no_tool_calls",
                adapters.sensitive_data(),
                [
                    (
                        "$ai_generation",
                        {
                            "$ai_output_choices": [
                                {"role": "assistant", "content": "Ask jane.doe@acme.io", "tool_calls": []}
                            ]
                        },
                    )
                ],
                False,
            ),
            (
                "otel_tool_call_parts_repeat",
                REPEATS,
                [_otel_call("search", {"q": "a"}, f"c{i}") for i in range(3)],
                False,
            ),
        ]
    )
    def test_verdict(self, _name: str, check: adapters.AdaptedCheck, events: list, expected: bool | None) -> None:
        assert _verdict(check, events) is expected
