import json
from pathlib import Path

from django.test import SimpleTestCase

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from openai.types.responses import ResponseFunctionToolCall
from parameterized import parameterized
from posthoganalytics.ai.langchain.callbacks import _convert_message_to_dict

from products.ai_observability.backend.facade.evaluation_runtime import execute_hog_eval_bytecode
from products.ai_observability.backend.hog import compile_ai_observability_hog

GENERATION_ID = "10000000-0000-4000-8000-000000000001"
JOB_ID = "20000000-0000-4000-8000-000000000002"
UNCITED_GENERATION_ID = "30000000-0000-4000-8000-000000000003"
TRACE_ID = "trace-example"
SOURCE_PATH = Path(__file__).resolve().parents[1] / "inline_ids_cited.hog"
Step = tuple[str, dict[str, str], str | None]


def report_events(steps: list[Step], protocol: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = [
        {"event": "$ai_span", "input": "[]", "output": "[]"},
        {"event": "$ai_generation", "input": "null", "output": "{}"},
    ]
    messages: list[dict[str, str]] = []
    callback_messages: list[BaseMessage] = []
    for index, (name, arguments, result) in enumerate(steps):
        call_id = f"call-{index}"
        current_input = messages
        output: object = [
            {"tool_calls": [{"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        ]
        if protocol.startswith("langchain"):
            flat_calls = [{"name": name, "args": arguments, "id": call_id, "type": "tool_call"}]
            call_message = AIMessage(content="", tool_calls=flat_calls)
            if protocol == "langchain_flat":
                call_message.additional_kwargs["tool_calls"] = flat_calls
            current_input = [_convert_message_to_dict(message) for message in callback_messages]
            output = [_convert_message_to_dict(call_message)]
            callback_messages.append(call_message)
        elif protocol in ("responses_native", "responses_envelope"):
            calls = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=name,
                    arguments=json.dumps(arguments),
                    call_id=call_id,
                    id=f"fc-{index}",
                ).model_dump()
            ]
            output = {"output": calls} if protocol == "responses_envelope" else calls
        events.append(
            {
                "event": "$ai_generation",
                "input": json.dumps(current_input),
                "output": json.dumps(output),
            }
        )
        if result is not None:
            if protocol.startswith("langchain"):
                callback_messages.append(ToolMessage(content=result, tool_call_id=call_id))
            elif protocol.startswith("responses"):
                messages.append({"type": "function_call_output", "call_id": call_id, "output": result})
            else:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
    final_input = (
        [_convert_message_to_dict(message) for message in callback_messages]
        if protocol.startswith("langchain")
        else messages
    )
    events.append({"event": "$ai_generation", "input": json.dumps(final_input), "output": "[]"})
    return events


class TestInlineIdsCited(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{protocol}", steps, expected, protocol)
            for name, steps, expected in [
                (
                    "accepted_citation",
                    [
                        ("get_generation_detail", {"generation_id": GENERATION_ID}, "Generation details"),
                        ("add_citation", {"generation_id": GENERATION_ID}, "Citation 1 added: example"),
                        (
                            "add_section",
                            {"content": f"The generation `{GENERATION_ID}` failed."},
                            "Section 1/6 added: Summary",
                        ),
                    ],
                    True,
                ),
                (
                    "rejected_draft_then_corrected_section",
                    [
                        ("get_generation_detail", {"generation_id": GENERATION_ID}, "Generation details"),
                        ("get_generation_detail", {"generation_id": UNCITED_GENERATION_ID}, "Generation details"),
                        (
                            "add_section",
                            {"content": f"An uncited draft `{UNCITED_GENERATION_ID}`."},
                            "Error: uncited ID",
                        ),
                        ("add_citation", {"generation_id": GENERATION_ID}, "Citation 1 added: example"),
                        (
                            "add_section",
                            {"content": f"The generation `{GENERATION_ID}` failed."},
                            "Section 1/6 added: Summary",
                        ),
                    ],
                    True,
                ),
                (
                    "unrelated_data_uuid",
                    [
                        (
                            "add_section",
                            {"content": f"The payload contains job ID `{JOB_ID}`."},
                            "Section 1/6 added: Summary",
                        )
                    ],
                    None,
                ),
                (
                    "uncited_handled_id",
                    [
                        ("get_trace_detail", {"trace_id": TRACE_ID}, "Trace details"),
                        ("add_section", {"content": f"The trace `{TRACE_ID}` failed."}, "Section 1/6 added: Summary"),
                    ],
                    False,
                ),
                (
                    "rejected_citation",
                    [
                        ("get_generation_detail", {"generation_id": GENERATION_ID}, "Generation details"),
                        ("add_citation", {"generation_id": GENERATION_ID}, "Error: target not found"),
                        (
                            "add_section",
                            {"content": f"The generation `{GENERATION_ID}` failed."},
                            "Section 1/6 added: Summary",
                        ),
                    ],
                    False,
                ),
                (
                    "missing_section_result",
                    [
                        ("get_trace_detail", {"trace_id": TRACE_ID}, "Trace details"),
                        ("add_section", {"content": f"The trace `{TRACE_ID}` failed."}, None),
                    ],
                    None,
                ),
                (
                    "generation_citation_does_not_cite_its_parent_trace",
                    [
                        ("get_trace_detail", {"trace_id": TRACE_ID}, "Trace details"),
                        (
                            "add_citation",
                            {"generation_id": GENERATION_ID, "trace_id": TRACE_ID},
                            "Citation 1 added: example",
                        ),
                        ("add_section", {"content": f"The trace `{TRACE_ID}` failed."}, "Section 1/6 added: Summary"),
                    ],
                    False,
                ),
                ("no_report_sections", [], None),
            ]
            for protocol in (
                "chat_completions",
                "responses",
                "responses_native",
                "responses_envelope",
                "langchain",
                "langchain_flat",
            )
        ]
    )
    def test_scores_only_delivered_sections(
        self, _name: str, steps: list[Step], expected: bool | None, protocol: str
    ) -> None:
        bytecode = compile_ai_observability_hog(SOURCE_PATH.read_text(), "destination")
        result = execute_hog_eval_bytecode(
            bytecode, {"evaluation_events": report_events(steps, protocol)}, allows_na=True
        )
        self.assertIsNone(result["error"])
        self.assertIs(result["verdict"], expected)

    @parameterized.expand(
        [
            ("complete", True),
            ("partial", None),
            ("extra", None),
            ("duplicates", None),
            ("mixed", None),
            ("nonadjacent", None),
            ("nontext", None),
            ("invalid", None),
        ]
    )
    def test_callback_batches_require_unambiguous_results(self, shape: str, expected: bool | None) -> None:
        events = report_events(
            [
                ("get_generation_detail", {"generation_id": UNCITED_GENERATION_ID}, "Generation details"),
                ("add_citation", {"generation_id": GENERATION_ID}, "Citation 1 added: example"),
            ],
            "chat_completions",
        )
        calls = [
            {"name": "add_section", "args": {"content": f"Draft `{UNCITED_GENERATION_ID}`."}, "id": "batch-rejected"},
            {"name": "add_section", "args": {"content": f"Final `{GENERATION_ID}`."}, "id": "batch-accepted"},
        ]
        if shape == "duplicates":
            calls[1]["id"] = calls[0]["id"]
        assistant = AIMessage(content="", tool_calls=calls)
        if shape == "invalid":
            assistant.additional_kwargs["tool_calls"] = [{**calls[0], "id": None}, calls[1]]
        messages: list[BaseMessage] = [assistant]
        if shape == "nonadjacent":
            messages.append(HumanMessage(content="Continue with a new turn."))
        results = [
            ToolMessage(
                content="Error: uncited ID",
                tool_call_id=calls[0]["id"],
                additional_kwargs={"tool_call_id": calls[0]["id"]} if shape == "mixed" else {},
            ),
            ToolMessage(content="Section 1/6 added: Summary", tool_call_id=calls[1]["id"]),
        ]
        if shape in ("partial", "invalid"):
            results = results[1:]
        elif shape in ("extra", "mixed"):
            results.append(ToolMessage(content="Section 2/6 added: Extra", tool_call_id="batch-extra"))
        elif shape == "nontext":
            results.append(ToolMessage(content=[{"type": "text", "text": "Extra result"}], tool_call_id="batch-extra"))
        messages.extend(results)
        events.extend(
            [
                {"event": "$ai_generation", "input": "[]", "output": json.dumps([_convert_message_to_dict(assistant)])},
                {
                    "event": "$ai_generation",
                    "input": json.dumps([_convert_message_to_dict(message) for message in messages]),
                    "output": "[]",
                },
            ]
        )

        bytecode = compile_ai_observability_hog(SOURCE_PATH.read_text(), "destination")
        result = execute_hog_eval_bytecode(bytecode, {"evaluation_events": events}, allows_na=True)
        self.assertIsNone(result["error"])
        self.assertIs(result["verdict"], expected)
