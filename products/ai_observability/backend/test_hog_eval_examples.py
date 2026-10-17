"""Tests that all Hog evaluation examples compile and run correctly.

Examples are defined in hogEvalExamples.json (shared with the frontend).
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from parameterized import parameterized

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_bytecode
from posthog.temporal.ai_observability.run_evaluation import run_hog_eval
from posthog.temporal.ai_observability.run_session_evaluation import build_session_hog_globals
from posthog.temporal.ai_observability.run_trace_evaluation import build_trace_hog_globals

from products.cdp.backend.validation import compile_hog

EXAMPLES_PATH = Path(__file__).resolve().parents[1] / "frontend" / "evaluations" / "hogEvalExamples.json"
EXAMPLES: list[dict] = json.loads(EXAMPLES_PATH.read_text())
EXAMPLE_LABELS = [e["label"] for e in EXAMPLES]


def _get_source(label: str) -> str:
    return next(e["source"] for e in EXAMPLES if e["label"] == label)


def _make_event(
    ai_input=None,
    ai_output_choices=None,
    ai_model="gpt-4",
    ai_total_cost_usd=0.01,
    ai_latency=1.5,
):
    if ai_input is None:
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is PostHog?"},
        ]
    if ai_output_choices is None:
        ai_output_choices = [
            {
                "message": {
                    "role": "assistant",
                    "content": "PostHog is an open-source product analytics platform that helps teams understand user behavior.",
                },
                "index": 0,
            },
        ]
    return {
        "uuid": str(uuid.uuid4()),
        "event": "$ai_generation",
        "properties": {
            "$ai_input": ai_input,
            "$ai_output_choices": ai_output_choices,
            "$ai_model": ai_model,
            "$ai_total_cost_usd": ai_total_cost_usd,
            "$ai_latency": ai_latency,
        },
        "timestamp": datetime.now().isoformat(),
        "team_id": 1,
        "distinct_id": "test-user",
    }


# Event whose output satisfies most examples (contains keywords, tool names, enough length, no PII, no errors, etc.)
CLEAN_EVENT = _make_event(
    ai_output_choices=[
        {
            "message": {
                "role": "assistant",
                "content": (
                    "Hello world! I called get_weather and get_news to help you. "
                    "PostHog is an open-source product analytics platform that helps teams "
                    "understand user behavior through event tracking and feature flags."
                ),
            },
            "index": 0,
        },
    ],
)
CLEAN_EVENT["properties"]["$ai_tools_called"] = "get_weather,get_news"


def _make_clean_trace_globals(bytecode: list[Any]) -> dict[str, Any]:
    trace = LLMTrace(
        id="trace-123",
        createdAt=CLEAN_EVENT["timestamp"],
        distinctId="test-user",
        totalCost=0.01,
        totalLatency=1.5,
        events=[
            LLMTraceEvent(
                id="span-1",
                event="$ai_span",
                createdAt=CLEAN_EVENT["timestamp"],
                properties={"$ai_span_name": "agent"},
            ),
            LLMTraceEvent(
                id=CLEAN_EVENT["uuid"],
                event=CLEAN_EVENT["event"],
                createdAt=CLEAN_EVENT["timestamp"],
                properties=CLEAN_EVENT["properties"],
            ),
        ],
    )
    return build_trace_hog_globals(trace, "trace-123", bytecode=bytecode)


def _make_clean_session_globals(bytecode: list[Any]) -> dict[str, Any]:
    """Two traces, so an example that reasons over a whole conversation sees more than one turn."""
    traces = [
        LLMTrace(
            id=f"trace-{index}",
            createdAt=CLEAN_EVENT["timestamp"],
            distinctId="test-user",
            totalCost=0.01,
            totalLatency=1.5,
            events=[
                LLMTraceEvent(
                    id=f"{CLEAN_EVENT['uuid']}-{index}",
                    event=CLEAN_EVENT["event"],
                    createdAt=CLEAN_EVENT["timestamp"],
                    properties=CLEAN_EVENT["properties"],
                )
            ],
        )
        for index in (1, 2)
    ]
    return build_session_hog_globals(traces, "session-123", bytecode=bytecode)


class TestHogEvalExamplesCompile:
    @parameterized.expand(EXAMPLE_LABELS)
    def test_compiles(self, label):
        source = _get_source(label)
        bytecode = compile_hog(source, "destination")
        assert len(bytecode) > 0


class TestHogEvalExamplesRun:
    @parameterized.expand(EXAMPLE_LABELS)
    def test_returns_bool_without_error(self, label):
        source = _get_source(label)
        bytecode = compile_hog(source, "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)

        assert result["error"] is None, f"'{label}' errored: {result['error']}"
        assert isinstance(result["verdict"], bool), f"'{label}' returned non-bool: {result['verdict']}"

    @parameterized.expand(EXAMPLE_LABELS)
    def test_returns_bool_without_error_for_trace(self, label):
        bytecode = compile_hog(_get_source(label), "destination")
        result = execute_hog_eval_bytecode(bytecode, _make_clean_trace_globals(bytecode), allows_na=False)

        assert result["error"] is None, f"'{label}' errored for a trace: {result['error']}"
        assert isinstance(result["verdict"], bool), f"'{label}' returned non-bool for a trace: {result['verdict']}"

    @parameterized.expand(EXAMPLE_LABELS)
    def test_returns_bool_without_error_for_session(self, label):
        """A session builds only `target` and `evaluation_events` — no `events` or `trace`. An
        example reaching for a trace-only global would come back undefined here rather than error,
        so assert on the verdict type as well: that is what catches it."""
        bytecode = compile_hog(_get_source(label), "destination")
        result = execute_hog_eval_bytecode(bytecode, _make_clean_session_globals(bytecode), allows_na=False)

        assert result["error"] is None, f"'{label}' errored for a session: {result['error']}"
        assert isinstance(result["verdict"], bool), f"'{label}' returned non-bool for a session: {result['verdict']}"


class TestHogEvalExamplesBehavior:
    @parameterized.expand(
        [
            ("Output not empty",),
            ("Output quality",),
            ("Error detection",),
            ("Refusal detection",),
            ("Regex safety checks",),
            ("Cost & latency guard",),
            ("Contains keywords",),
            ("Tools called",),
        ]
    )
    def test_passes_on_clean_output(self, label):
        bytecode = compile_hog(_get_source(label), "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)
        assert result["error"] is None
        assert result["verdict"] is True

    @parameterized.expand(
        [
            ("Output not empty", ""),
            ("Output quality", "short"),
            ("Error detection", "An error occurred\nTraceback follows"),
            ("Refusal detection", "I'm sorry, but I cannot help with that request."),
        ]
    )
    def test_fails_on_bad_output(self, label, bad_output):
        bytecode = compile_hog(_get_source(label), "destination")
        # Use $ai_output directly so the output global is the plain string, not a JSON-serialized choices array
        event = _make_event()
        event["properties"].pop("$ai_output_choices", None)
        event["properties"]["$ai_output"] = bad_output
        result = run_hog_eval(bytecode, event)
        assert result["error"] is None
        assert result["verdict"] is False, f"'{label}' should have failed but passed"

    def test_cost_guard_fails_on_expensive(self):
        bytecode = compile_hog(_get_source("Cost & latency guard"), "destination")
        event = _make_event(ai_total_cost_usd=0.10, ai_latency=1.0)
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False
        assert "exceeds budget" in result["reasoning"]

    def test_output_not_empty_fails_on_empty_choice_content(self):
        bytecode = compile_hog(_get_source("Output not empty"), "destination")
        event = _make_event(ai_output_choices=[{"message": {"role": "assistant", "content": ""}}])

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is False

    @parameterized.expand([("Output not empty",), ("Min output length",), ("Output quality",)])
    def test_generation_quality_checks_fail_without_generation_events(self, label: str) -> None:
        bytecode = compile_hog(_get_source(label), "destination")
        trace = LLMTrace(
            id="trace-123",
            createdAt=CLEAN_EVENT["timestamp"],
            distinctId="test-user",
            events=[
                LLMTraceEvent(
                    id="span-1",
                    event="$ai_span",
                    createdAt=CLEAN_EVENT["timestamp"],
                    properties={"$ai_span_name": "agent"},
                )
            ],
        )

        result = execute_hog_eval_bytecode(
            bytecode, build_trace_hog_globals(trace, trace.id, bytecode=bytecode), allows_na=False
        )

        assert result["verdict"] is False
        assert "No generation events found" in result["reasoning"]

    @parameterized.expand([([{"type": "text", "text": ""}],), ({"choices": [{"text": ""}]},)])
    def test_output_not_empty_fails_on_empty_text_choice(self, output_choices):
        bytecode = compile_hog(_get_source("Output not empty"), "destination")
        event = _make_event(ai_output_choices=output_choices)

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is False

    @parameterized.expand(
        [
            ("scalar", 42),
            ("boolean_choice", [False]),
            ("zero_content", [{"message": {"role": "assistant", "content": 0}}]),
        ]
    )
    def test_output_not_empty_passes_on_non_string_output(self, _name: str, output_choices: Any) -> None:
        bytecode = compile_hog(_get_source("Output not empty"), "destination")
        event = _make_event(ai_output_choices=output_choices)

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is True

    @parameterized.expand(
        [
            ("json_openai", "Valid JSON output", [{"message": {"role": "assistant", "content": '{"ok": true}'}}], True),
            (
                "json_otel_parts",
                "Valid JSON output",
                [{"role": "assistant", "parts": [{"type": "text", "content": '{"ok": true}'}]}],
                True,
            ),
            (
                "json_fenced",
                "Valid JSON output",
                [{"message": {"role": "assistant", "content": '```json\n{"ok": true}\n```'}}],
                True,
            ),
            (
                "json_fence_inside_string",
                "Valid JSON output",
                [{"message": {"role": "assistant", "content": '{"md": "Use ``` for code blocks"}'}}],
                True,
            ),
            (
                "json_prose",
                "Valid JSON output",
                [{"message": {"role": "assistant", "content": "Here you go: ok"}}],
                False,
            ),
            ("empty_openai", "Empty or failed output", [{"message": {"role": "assistant", "content": ""}}], False),
            ("empty_otel_parts", "Empty or failed output", [{"role": "assistant", "parts": []}], False),
            (
                "json_responses_tool_output_then_reply",
                "Valid JSON output",
                [
                    {"type": "function_call_output", "call_id": "call_1", "output": "Saved."},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"ok": true}'}],
                    },
                ],
                True,
            ),
            ("json_flat_text_type_payload", "Valid JSON output", [{"type": "text", "value": "Hello"}], True),
            ("non_empty_flat_text_type_payload", "Empty or failed output", [{"type": "text", "value": "Hello"}], True),
            ("json_flat_text_block_prose", "Valid JSON output", [{"type": "text", "text": "not JSON"}], False),
            (
                "non_empty_responses_refusal_block",
                "Empty or failed output",
                [{"role": "assistant", "content": [{"type": "refusal", "refusal": "I can't help with that."}]}],
                True,
            ),
            ("json_flat_empty_text_block", "Valid JSON output", [{"type": "text", "text": ""}], False),
            ("empty_flat_empty_text_block", "Empty or failed output", [{"type": "text", "text": ""}], False),
            (
                "json_flat_blocks_with_thinking",
                "Valid JSON output",
                [{"type": "thinking", "thinking": "Checking."}, {"type": "text", "text": '{"ok": true}'}],
                True,
            ),
            (
                "json_string_encoded_prose",
                "Valid JSON output",
                '[{"role": "assistant", "content": "Here you go"}]',
                False,
            ),
            (
                "json_string_encoded_json_reply",
                "Valid JSON output",
                '[{"role": "assistant", "content": "{\\"ok\\": true}"}]',
                True,
            ),
            (
                "json_string_encoded_element",
                "Valid JSON output",
                ['{"role": "assistant", "content": "Here you go"}'],
                False,
            ),
            ("empty_string_encoded", "Empty or failed output", '[{"role": "assistant", "content": ""}]', False),
            ("json_structured_with_type_key", "Valid JSON output", [{"type": "invoice", "amount": 10}], True),
            ("non_empty_structured_with_type_key", "Empty or failed output", [{"type": "invoice", "amount": 10}], True),
            (
                "json_structured_with_object_role",
                "Valid JSON output",
                [{"name": "Ann", "role": {"title": "admin"}}],
                True,
            ),
            (
                "json_content_with_list_type",
                "Valid JSON output",
                [{"role": "assistant", "content": {"type": ["object", "null"], "properties": {}}}],
                True,
            ),
            ("json_roleless_parts_payload", "Valid JSON output", [{"parts": ["wheel", "tire"]}], True),
            ("json_numeric_content", "Valid JSON output", [{"role": "assistant", "content": 42}], True),
            (
                "json_numeric_text_block",
                "Valid JSON output",
                [{"role": "assistant", "content": [{"type": "text", "text": 0}]}],
                True,
            ),
            (
                "structured_output_with_list_type_field",
                "Valid JSON output",
                [{"type": ["a", "b"], "value": 1}],
                True,
            ),
            (
                "content_block_with_list_type",
                "Empty or failed output",
                [{"role": "assistant", "content": [{"type": ["text"], "text": "x"}, {"type": "text", "text": "Hi"}]}],
                True,
            ),
            (
                "json_with_tool_call_block",
                "Valid JSON output",
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": '{"ok": true}'},
                            {"type": "function", "id": "call_1", "function": {"name": "save", "arguments": "{}"}},
                        ],
                    }
                ],
                True,
            ),
            (
                "json_responses_function_call_item",
                "Valid JSON output",
                [
                    {"type": "function_call", "call_id": "call_1", "name": "save", "arguments": "{}"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"ok": true}'}],
                    },
                ],
                True,
            ),
            (
                "json_empty_text_block",
                "Valid JSON output",
                [{"role": "assistant", "content": [{"type": "text", "text": ""}]}],
                False,
            ),
            (
                "empty_anthropic_empty_text_block",
                "Empty or failed output",
                [{"role": "assistant", "content": [{"type": "text", "text": ""}]}],
                False,
            ),
            (
                "json_anthropic_thinking",
                "Valid JSON output",
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Checking the fields.", "signature": "sig"},
                            {"type": "text", "text": '{"ok": true}'},
                        ],
                    }
                ],
                True,
            ),
            (
                "json_anthropic_redacted_thinking",
                "Valid JSON output",
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "redacted_thinking", "data": "opaque"},
                            {"type": "text", "text": '{"ok": true}'},
                        ],
                    }
                ],
                True,
            ),
            (
                "json_openai_responses_reasoning",
                "Valid JSON output",
                [
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Checking the fields."}]},
                    {"role": "assistant", "content": [{"type": "output_text", "text": '{"ok": true}'}]},
                ],
                True,
            ),
            (
                "json_gemini_thought",
                "Valid JSON output",
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Checking the fields.", "thought": True},
                            {"type": "text", "text": '{"ok": true}'},
                        ],
                    }
                ],
                True,
            ),
            (
                "empty_anthropic_thinking_only",
                "Empty or failed output",
                [{"role": "assistant", "content": [{"type": "thinking", "thinking": "Thinking it over."}]}],
                False,
            ),
            (
                "json_otel_with_reasoning",
                "Valid JSON output",
                [
                    {
                        "role": "assistant",
                        "parts": [
                            {"type": "text", "content": '{"ok": true}'},
                            {"type": "reasoning", "content": "Checking the result."},
                        ],
                    }
                ],
                True,
            ),
            (
                "empty_otel_two_messages",
                "Empty or failed output",
                [{"role": "assistant", "parts": []}, {"role": "assistant", "parts": []}],
                False,
            ),
            (
                "empty_otel_reasoning_only",
                "Empty or failed output",
                [{"role": "assistant", "parts": [{"type": "reasoning", "content": "Thinking it over."}]}],
                False,
            ),
            (
                "non_empty_otel_parts",
                "Empty or failed output",
                [{"role": "assistant", "parts": [{"type": "text", "content": "Hi"}]}],
                True,
            ),
        ]
    )
    def test_output_body_checks_handle_provider_shapes(
        self, _name: str, label: str, output_choices: Any, expected: bool
    ) -> None:
        bytecode = compile_hog(_get_source(label), "destination")

        result = run_hog_eval(bytecode, _make_event(ai_output_choices=output_choices))

        assert result["error"] is None
        assert result["verdict"] is expected

    @parameterized.expand(
        [
            ("json_reply_with_role_field", "Valid JSON output", '{"role": "admin", "permissions": ["read"]}', True),
            (
                "non_empty_reply_with_role_field",
                "Empty or failed output",
                '{"role": "admin", "permissions": ["read"]}',
                True,
            ),
            (
                "json_reply_with_role_and_content_fields",
                "Valid JSON output",
                '{"role": "admin", "content": "Permissions assigned"}',
                True,
            ),
            ("json_reply_array", "Valid JSON output", "[1, 2]", True),
            (
                "json_assistant_message_prose",
                "Valid JSON output",
                {"role": "assistant", "content": "The albatross flies."},
                False,
            ),
        ]
    )
    def test_output_body_checks_read_ai_output_as_written(
        self, _name: str, label: str, ai_output: Any, expected: bool
    ) -> None:
        bytecode = compile_hog(_get_source(label), "destination")
        event = _make_event()
        event["properties"].pop("$ai_output_choices")
        event["properties"]["$ai_output"] = ai_output

        result = run_hog_eval(bytecode, event)

        assert result["error"] is None
        assert result["verdict"] is expected

    @parameterized.expand([("Empty or failed output",), ("Valid JSON output",)])
    def test_output_body_checks_pass_a_step_that_only_calls_tools(self, label: str) -> None:
        bytecode = compile_hog(_get_source(label), "destination")
        event = _make_event(
            ai_output_choices=[
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}}],
                }
            ]
        )
        event["properties"]["$ai_tools_called"] = "get_weather"

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is True

    @parameterized.expand(
        [
            ("empty_string", "", True),
            ("false", False, True),
            ("zero", 0, True),
            ("message", "Rate limit exceeded", False),
        ]
    )
    def test_failed_output_treats_falsy_error_as_success(self, _name: str, ai_error: Any, expected: bool) -> None:
        bytecode = compile_hog(_get_source("Empty or failed output"), "destination")
        event = _make_event()
        event["properties"]["$ai_error"] = ai_error

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is expected

    @parameterized.expand(
        [("under_limit", "search,search,fetch", True), ("over_limit", ",".join(["search"] * 6), False)]
    )
    def test_repeated_tool_calls_limit(self, _name: str, tools_called: str, expected: bool) -> None:
        bytecode = compile_hog(_get_source("Repeated tool calls"), "destination")
        event = _make_event()
        event["properties"]["$ai_tools_called"] = tools_called

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is expected

    def test_refusal_detection_handles_openai_refusal_field(self):
        bytecode = compile_hog(_get_source("Refusal detection"), "destination")
        event = _make_event(
            ai_output_choices=[
                {"message": {"role": "assistant", "content": None, "refusal": "I cannot help with that request."}}
            ]
        )

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is False

    def test_error_detection_handles_string_error_flag(self):
        bytecode = compile_hog(_get_source("Error detection"), "destination")
        event = _make_event()
        event["properties"]["$ai_is_error"] = "true"

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is False

    def test_tools_called_does_not_match_names_only_mentioned_in_output(self):
        bytecode = compile_hog(_get_source("Tools called"), "destination")
        event = _make_event(
            ai_output_choices=[{"message": {"role": "assistant", "content": "I could call get_weather and get_news."}}]
        )

        result = run_hog_eval(bytecode, event)

        assert result["verdict"] is False

    def test_conversation_length_fails_on_long(self):
        bytecode = compile_hog(_get_source("Conversation length"), "destination")
        long_conversation = [{"role": "user", "content": f"Message {i}"} for i in range(15)]
        event = _make_event(ai_input=long_conversation)
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False
        assert "Exceeds limit" in result["reasoning"]

    def test_conversation_length_skips_truncated_json(self):
        bytecode = compile_hog(_get_source("Conversation length"), "destination")
        event = _make_event(ai_input='[{"role":"user","content":"truncated... [truncated]')

        result = run_hog_eval(bytecode, event)

        assert result["error"] is None
        assert result["verdict"] is True
        assert "Could not parse input" in result["reasoning"]

    def test_regex_safety_fails_on_email(self):
        bytecode = compile_hog(_get_source("Regex safety checks"), "destination")
        event = _make_event(
            ai_output_choices=[
                {"message": {"role": "assistant", "content": "Contact us at test@example.com"}, "index": 0}
            ],
        )
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False

    def test_quickstart_prints_messages_and_choices(self):
        bytecode = compile_hog(_get_source("Quickstart"), "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)
        assert result["verdict"] is True
        assert "Event 0: $ai_generation" in result["reasoning"]
        assert "Input:" in result["reasoning"]
        assert "Output:" in result["reasoning"]
        assert "Model: gpt-4" in result["reasoning"]

    def test_na_guard_returns_null_when_model_missing(self):
        bytecode = compile_hog(_get_source("N/A guard"), "destination")
        event = _make_event(ai_model=None)
        del event["properties"]["$ai_model"]
        result = run_hog_eval(bytecode, event, allows_na=True)
        assert result["error"] is None
        assert result["verdict"] is None
        assert "not applicable" in result["reasoning"]

    def test_na_guard_passes_on_allowed_model(self):
        bytecode = compile_hog(_get_source("N/A guard"), "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)
        assert result["error"] is None
        assert result["verdict"] is True

    def test_na_guard_fails_on_disallowed_model(self):
        bytecode = compile_hog(_get_source("N/A guard"), "destination")
        event = _make_event(ai_model="llama-3")
        result = run_hog_eval(bytecode, event)
        assert result["error"] is None
        assert result["verdict"] is False
        assert "not in the allowed list" in result["reasoning"]

    def test_quickstart_handles_plain_string_input_and_output(self):
        bytecode = compile_hog(_get_source("Quickstart"), "destination")
        event = _make_event()
        event["properties"].pop("$ai_output_choices", None)
        event["properties"]["$ai_input"] = "What is PostHog?"
        event["properties"]["$ai_output"] = "PostHog is a product analytics platform."
        result = run_hog_eval(bytecode, event)
        assert result["error"] is None
        assert result["verdict"] is True
        assert "Input: What is PostHog?" in result["reasoning"]
        assert "Output: PostHog is a product analytics platform." in result["reasoning"]

    @parameterized.expand([("Quickstart",), ("Print messages",)])
    def test_diagnostic_output_fits_temporal_payload_for_max_unicode_trace(self, label):
        bytecode = compile_hog(_get_source(label), "destination")
        unicode_text = "😀" * 101
        trace = LLMTrace(
            id="trace-123",
            createdAt=CLEAN_EVENT["timestamp"],
            distinctId="test-user",
            events=[
                LLMTraceEvent(
                    id=f"generation-{index}",
                    event="$ai_generation",
                    createdAt=CLEAN_EVENT["timestamp"],
                    properties={"$ai_input": unicode_text, "$ai_output": unicode_text},
                )
                for index in range(500)
            ],
        )

        result = execute_hog_eval_bytecode(
            bytecode, build_trace_hog_globals(trace, trace.id, bytecode=bytecode), allows_na=False
        )

        assert result["error"] is None
        assert len(json.dumps(result["reasoning"]).encode()) < 2 * 1024 * 1024
