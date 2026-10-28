import json
from typing import Any

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.ticket_brief.schema import TicketBriefSerializer
from products.conversations.backend.ticket_brief.writer import _build_brief, write_brief

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
            patch(f"{MODULE}.brief_enabled", return_value=False),
            patch(f"{MODULE}.get_async_anthropic_gateway_client") as client,
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "disabled"
        assert client.call_count == 0

    async def test_a_failing_gate_check_returns_rather_than_raises(self) -> None:
        # The gate is a database read, and an exception from it would fail the activity. Temporal
        # would then retry, paying for a model call to recover from something like a lock wait.
        with (
            patch(f"{MODULE}.brief_enabled", side_effect=RuntimeError("connection reset")),
            patch(f"{MODULE}.get_async_anthropic_gateway_client") as client,
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "gate_failed"
        assert client.call_count == 0

    async def test_a_failing_store_returns_rather_than_raises(self) -> None:
        # Same reason as the gate check, and this one happens after the model call, so a raise
        # here buys a second call to redo work that already succeeded.
        with (
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.get_async_anthropic_gateway_client"),
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
            patch(f"{MODULE}.brief_enabled", return_value=True),
            patch(f"{MODULE}.get_async_anthropic_gateway_client", side_effect=RuntimeError("gateway down")),
        ):
            output = await write_brief(team_id=1, ticket_id="t", ticket_context="ctx")
        assert output.written is False
        assert output.reason == "llm_failed"
