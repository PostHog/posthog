import json
from types import SimpleNamespace
from typing import Any

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.ticket_brief.limits import (
    MAX_AREA,
    MAX_ASK,
    MAX_ERROR_MESSAGE,
    MAX_FACT,
    MAX_FACTS,
    MAX_PURPOSE,
    MAX_QUESTION,
    MAX_QUESTIONS,
    MAX_TRIED,
)
from products.conversations.backend.ticket_brief.schema import TicketBriefSerializer
from products.conversations.backend.ticket_brief.writer import (
    MAX_CONTEXT_CHARS,
    MAX_OUTPUT_TOKENS,
    _bounded_context,
    _build_brief,
    write_brief,
)

BASE = {"ask": "Explain why the export is empty.", "area": "Batch exports", "questions": ["Why?"]}

MODULE = "products.conversations.backend.ticket_brief.writer"


class TestWriteBrief(SimpleTestCase):
    @parameterized.expand(
        [
            ("ask_over_cap", {"ask": "x" * 600}, "ask", 400),
            ("area_over_cap", {"area": "x" * 200}, "area", 80),
            ("too_many_questions", {"questions": [f"q{i}?" for i in range(20)]}, "questions", 6),
            ("too_many_facts", {"facts": [f"f{i}" for i in range(20)]}, "facts", 5),
            ("too_many_tried", {"tried": [f"t{i}" for i in range(20)]}, "tried", 5),
            ("error_over_cap", {"error_message": "x" * 900}, "error_message", 600),
            ("purpose_over_cap", {"purpose": "x" * 500}, "purpose", 300),
        ]
    )
    def test_shaping_brings_an_over_long_response_inside_the_caps(
        self, _name: str, overrides: dict[str, Any], field: str, cap: int
    ) -> None:
        # The model is told the caps but can ignore them, and the serializer rejects the whole
        # brief when it does. Shaping first means the ticket keeps a clipped brief instead of none.
        brief = _build_brief({**BASE, **overrides})
        value = brief[field]
        assert len(value) <= cap
        serializer = TicketBriefSerializer(data=brief)
        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [
            ("question_over_cap", {"questions": ["x" * 250]}, "questions", 200),
            ("tried_over_cap", {"tried": ["x" * 200]}, "tried", 160),
            ("facts_over_cap", {"facts": ["x" * 200]}, "facts", 160),
        ]
    )
    def test_shaping_clips_each_entry_of_a_list_not_only_the_list(
        self, _name: str, overrides: dict[str, Any], field: str, cap: int
    ) -> None:
        # A list can sit inside its count cap while one entry runs past the per-entry cap, which
        # the serializer rejects, costing the ticket the whole brief.
        brief = _build_brief({**BASE, **overrides})
        assert brief[field]
        assert all(len(entry) <= cap for entry in brief[field])
        serializer = TicketBriefSerializer(data=brief)
        assert serializer.is_valid(), serializer.errors

    def test_shaping_drops_blank_entries_before_it_caps_the_count(self) -> None:
        # A blank entry that spends one of the places pushes a real question out of the brief.
        parsed = {**BASE, "questions": ["", "q1?", "", "q2?", "", "q3?", "", "q4?", "", "q5?", "", "q6?"]}
        brief = _build_brief(parsed)
        assert brief["questions"] == ["q1?", "q2?", "q3?", "q4?", "q5?", "q6?"]

    @parameterized.expand([("purpose",), ("error_message",)])
    def test_an_empty_optional_field_is_omitted_rather_than_stored_blank(self, field: str) -> None:
        # The model returns "" for a purpose it could not find. Storing that renders an empty
        # labelled row in the sidebar, so it has to be absent instead.
        brief = _build_brief({**BASE, field: ""})
        assert field not in brief

    async def test_a_team_without_the_flag_gets_no_brief_and_no_model_call(self) -> None:
        # The gate is the whole safety story for shipping this: until the flag is rolled out,
        # merging must change nothing a support engineer sees and must spend no tokens.
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=True),
            patch(f"{MODULE}.brief_enabled", return_value=False),
            patch(f"{MODULE}.build_conversations_client") as client,
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "disabled"
        assert client.call_count == 0

    async def test_a_failing_gate_check_returns_rather_than_raises(self) -> None:
        # The gate is a database read, and an exception from it would fail the activity. Temporal
        # would then retry, paying for a model call to recover from something like a lock wait.
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=True),
            patch(f"{MODULE}.brief_enabled", side_effect=RuntimeError("connection reset")),
            patch(f"{MODULE}.build_conversations_client") as client,
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "gate_failed"
        assert client.call_count == 0

    async def test_a_failing_store_returns_rather_than_raises(self) -> None:
        # Same reason as the gate check, and this one happens after the model call, so a raise
        # here buys a second call to redo work that already succeeded.
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=True),
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.build_conversations_client"),
            patch(f"{MODULE}.create_message", new_callable=AsyncMock),
            patch(f"{MODULE}.anthropic_text", return_value=json.dumps(BASE)),
            patch(f"{MODULE}._store_brief", side_effect=RuntimeError("deadlock detected")),
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "store_failed"

    async def test_a_failing_model_call_returns_rather_than_raises(self) -> None:
        # The brief rides inside the reply pipeline. An exception here would fail a run whose
        # real job is drafting a reply, so a gateway blip must cost the brief and nothing else.
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=True),
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.build_conversations_client", side_effect=RuntimeError("gateway down")),
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "llm_failed"

    @parameterized.expand([("gate_respected", True), ("gate_waived", False)])
    async def test_an_organization_without_ai_approval_gets_no_brief_and_no_model_call(
        self, _name: str, respect_gate: bool
    ) -> None:
        # Every other AI path in this product checks approval. respect_gate=False is how the
        # staff button reads a brief before the flag reaches a team, so without the waived case
        # that path would send a ticket to a model for an organization that never consented.
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=False),
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.build_conversations_client") as client,
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx", respect_gate=respect_gate)
        assert output.written is False
        assert output.reason == "ai_not_approved"
        assert client.call_count == 0

    async def test_a_truncated_response_is_named_rather_than_reported_as_a_failure(self) -> None:
        # A response cut at the token budget cannot parse, so it would otherwise land as
        # llm_failed and point at the gateway instead of at the budget.
        message = SimpleNamespace(stop_reason="max_tokens")
        with (
            patch(f"{MODULE}.ai_processing_approved", return_value=True),
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.build_conversations_client"),
            patch(f"{MODULE}.create_message", new_callable=AsyncMock, return_value=message),
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "truncated"

    def test_the_output_budget_covers_every_field_at_its_cap(self) -> None:
        # A budget below the contract truncates a detailed brief mid-object, and a truncated
        # object does not parse, so the whole brief is lost rather than clipped.
        widest = json.dumps(
            {
                "ask": "x" * MAX_ASK,
                "area": "x" * MAX_AREA,
                "purpose": "x" * MAX_PURPOSE,
                "error_message": "x" * MAX_ERROR_MESSAGE,
                "questions": ["x" * MAX_QUESTION] * MAX_QUESTIONS,
                "facts": ["x" * MAX_FACT] * MAX_FACTS,
                "tried": ["x" * MAX_FACT] * MAX_TRIED,
            }
        )
        assert MAX_OUTPUT_TOKENS >= len(widest) // 4

    def test_bounding_the_context_keeps_the_newest_messages(self) -> None:
        # format_conversation already drops the oldest messages to fit its own budget, so the
        # end of the string is the customer's latest word. Cutting the end would brief an
        # engineer on a request the customer has since changed.
        context = "OLDEST" + ("x" * MAX_CONTEXT_CHARS) + "NEWEST"
        bounded = _bounded_context(context)
        assert bounded.endswith("NEWEST")
        assert "OLDEST" not in bounded
        assert len(bounded) <= MAX_CONTEXT_CHARS + 4
