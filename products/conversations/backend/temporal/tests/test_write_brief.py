from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.api.ticket_brief import TicketBriefSerializer
from products.conversations.backend.temporal.ai_reply.activities.write_brief import _build_brief, _write_brief
from products.conversations.backend.temporal.ai_reply.schemas import WriteBriefInput

BASE = {"ask": "Explain why the export is empty.", "area": "Batch exports", "questions": ["Why?"]}


class TestWriteBrief(SimpleTestCase):
    @parameterized.expand(
        [
            ("ask_over_cap", {"ask": "x" * 600}, "ask", 400),
            ("area_over_cap", {"area": "x" * 200}, "area", 80),
            ("too_many_questions", {"questions": [f"q{i}?" for i in range(20)]}, "questions", 6),
            ("too_many_facts", {"facts": [f"f{i}" for i in range(20)]}, "facts", 5),
            ("too_many_tried", {"tried": [f"t{i}" for i in range(20)]}, "tried", 5),
            ("error_over_cap", {"error_message": "x" * 900}, "error_message", 600),
        ]
    )
    def test_shaping_brings_an_over_long_response_inside_the_caps(self, _name, overrides, field, cap):
        # The model is told the caps but can ignore them, and the serializer rejects the whole
        # brief when it does. Shaping first means the ticket keeps a clipped brief instead of none.
        brief = _build_brief({**BASE, **overrides})
        value = brief[field]
        assert len(value) <= cap
        serializer = TicketBriefSerializer(data=brief)
        assert serializer.is_valid(), serializer.errors

    @parameterized.expand([("purpose",), ("error_message",)])
    def test_an_empty_optional_field_is_omitted_rather_than_stored_blank(self, field):
        # The model returns "" for a purpose it could not find. Storing that renders an empty
        # labelled row in the sidebar, so it has to be absent instead.
        brief = _build_brief({**BASE, field: ""})
        assert field not in brief

    async def test_a_team_that_has_not_opted_in_gets_no_brief_and_no_model_call(self):
        # The gate is the whole safety story for shipping this: until a team turns the setting
        # on, merging must change nothing a support engineer sees and must spend no tokens.
        with (
            patch(
                "products.conversations.backend.temporal.ai_reply.activities.write_brief._brief_enabled",
                return_value=False,
            ),
            patch(
                "products.conversations.backend.temporal.ai_reply.activities.write_brief.get_async_anthropic_gateway_client"
            ) as client,
        ):
            output = await _write_brief(WriteBriefInput(team_id=1, ticket_id="t", ticket_context="ctx"))
        assert output.written is False
        assert output.reason == "disabled"
        assert client.call_count == 0

    async def test_a_failing_model_call_returns_rather_than_raises(self):
        # The brief rides inside the reply pipeline. An exception here would fail a run whose
        # real job is drafting a reply, so a gateway blip must cost the brief and nothing else.
        with (
            patch(
                "products.conversations.backend.temporal.ai_reply.activities.write_brief._brief_enabled",
                return_value=True,
            ),
            patch(
                "products.conversations.backend.temporal.ai_reply.activities.write_brief.get_async_anthropic_gateway_client",
                side_effect=RuntimeError("gateway down"),
            ),
        ):
            output = await _write_brief(WriteBriefInput(team_id=1, ticket_id="t", ticket_context="ctx"))
        assert output.written is False
        assert output.reason == "llm_failed"
