import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.logic.evaluations.hog_runtime import execute_hog_eval_bytecode
from products.cdp.backend.validation import compile_hog

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
    for index, (name, arguments, result) in enumerate(steps):
        call_id = f"call-{index}"
        events.append(
            {
                "event": "$ai_generation",
                "input": json.dumps(messages),
                "output": json.dumps(
                    [{"tool_calls": [{"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}]}]
                ),
            }
        )
        if result is not None:
            if protocol == "responses":
                messages.append({"type": "function_call_output", "call_id": call_id, "output": result})
            else:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
    events.append({"event": "$ai_generation", "input": json.dumps(messages), "output": "[]"})
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
            for protocol in ("chat_completions", "responses")
        ]
    )
    def test_scores_only_delivered_sections(
        self, _name: str, steps: list[Step], expected: bool | None, protocol: str
    ) -> None:
        bytecode = compile_hog(SOURCE_PATH.read_text(), "destination")
        result = execute_hog_eval_bytecode(
            bytecode, {"evaluation_events": report_events(steps, protocol)}, allows_na=True
        )
        self.assertIsNone(result["error"])
        self.assertIs(result["verdict"], expected)
