import json
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import TicketBriefItemKind
from products.conversations.backend.ticket_brief.limits import (
    MAX_AREA,
    MAX_ASK,
    MAX_ERROR_MESSAGE,
    MAX_FACT,
    MAX_FACTS,
    MAX_PURPOSE,
    MAX_QUESTION,
    MAX_QUESTIONS,
    MAX_SCREENSHOTS,
    MAX_TRIED,
    MAX_URL_LENGTH,
)
from products.conversations.backend.ticket_brief.schema import TicketBriefSerializer
from products.conversations.backend.ticket_brief.writer import (
    _ITEM_KIND_PATHS,
    MAX_CONTEXT_CHARS,
    MAX_OUTPUT_TOKENS,
    _affected_items_for,
    _bounded_context,
    _build_brief,
    _screenshot_urls_for,
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

    @parameterized.expand(
        [
            ("feature_flag", "https://us.posthog.com/project/2/feature_flags/14", "feature_flag"),
            ("experiment", "https://us.posthog.com/project/2/experiments/88", "experiment"),
            ("insight", "https://us.posthog.com/project/2/insights/aB3xY", "insight"),
            ("dashboard", "https://us.posthog.com/project/2/dashboard/7", "dashboard"),
            ("survey", "https://us.posthog.com/project/2/surveys/5", "survey"),
            ("replay", "https://us.posthog.com/project/2/replay/0199aaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "replay"),
            ("project_page_with_no_object", "https://us.posthog.com/project/2/settings", "project"),
            ("a_link_out", "https://example.com/status/incident-4", "external"),
        ]
    )
    def test_the_page_the_customer_was_on_becomes_an_item_of_its_own_kind(
        self, _name: str, url: str, expected_kind: str
    ) -> None:
        # The panel labels the link by this kind, so a wrong one sends the engineer to the wrong
        # product area. A kind outside the enum is worse: the serializer rejects the object and
        # the ticket loses its whole brief.
        ticket = Ticket(session_context={"current_url": url})
        items = _affected_items_for(ticket)
        assert [item["kind"] for item in items] == [expected_kind]
        assert [item["url"] for item in items] == [url]
        assert TicketBriefSerializer(data={**BASE, "affected_items": items}).is_valid()

    @parameterized.expand(
        [
            ("not_a_url", "notaurl"),
            ("a_script_url", "javascript:alert(1)"),
            ("over_the_cap", "https://us.posthog.com/project/2/insights/" + "x" * MAX_URL_LENGTH),
            ("not_a_string", 12),
            ("absent", None),
        ]
    )
    def test_a_page_that_is_not_a_usable_url_yields_no_item(self, _name: str, current_url: object) -> None:
        # session_context arrives from the public widget endpoint, which only caps the length of
        # what it is sent. These values join the brief after the serializer has run, so nothing
        # else stops a script URL reaching the panel as a link.
        assert _affected_items_for(Ticket(session_context={"current_url": current_url})) == []

    def test_every_kind_the_classifier_can_return_is_one_the_serializer_accepts(self) -> None:
        # The classifier and the enum are edited in different files. A kind the serializer
        # rejects costs the ticket its whole brief, not just the link.
        kinds = {kind for _pattern, kind in _ITEM_KIND_PATHS} | {
            TicketBriefItemKind.PROJECT,
            TicketBriefItemKind.EXTERNAL,
        }
        assert kinds <= set(TicketBriefItemKind.values)


class TestBriefScreenshots(BaseTest):
    def _ticket(self) -> Ticket:
        return Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="brief-shots",
            distinct_id="brief-shots-d1",
        )

    def _message(self, ticket: Ticket, *image_urls: str, context: dict[str, Any] | None = None) -> None:
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            item_context={} if context is None else context,
            content="",
            rich_content={
                "type": "doc",
                "content": [{"type": "image", "attrs": {"src": url}} for url in image_urls],
            },
        )

    @parameterized.expand([("key_absent", {}), ("explicitly_public", {"is_private": False})])
    def test_a_public_message_keeps_its_screenshots_however_it_records_that(
        self, _name: str, context: dict[str, Any]
    ) -> None:
        # A JSON exclude drops the rows where the key is absent, because SQL NULL is not False,
        # so filtering private notes with `exclude` alone silently loses every screenshot on a
        # message that never set the key.
        ticket = self._ticket()
        self._message(ticket, "https://img.example.com/shot.png", context=context)
        assert _screenshot_urls_for(self.team.id, str(ticket.id)) == ["https://img.example.com/shot.png"]

    def test_screenshots_are_collected_oldest_first_and_only_from_what_the_customer_sent(self) -> None:
        # A teammate's private note is not the customer's evidence, and the model never sees it
        # either, so a brief that links it shows the engineer a screenshot the customer never
        # sent. Order matters because the panel numbers them as the customer sent them.
        ticket = self._ticket()
        self._message(ticket, "https://img.example.com/first.png")
        self._message(ticket, "https://img.example.com/internal.png", context={"is_private": True})
        self._message(ticket, "https://img.example.com/second.png", "https://img.example.com/first.png")
        assert _screenshot_urls_for(self.team.id, str(ticket.id)) == [
            "https://img.example.com/first.png",
            "https://img.example.com/second.png",
        ]

    def test_more_screenshots_than_the_cap_are_dropped_rather_than_costing_the_whole_brief(self) -> None:
        # The serializer rejects a list over the cap, and it runs on the whole brief, so one
        # chatty thread would otherwise leave the ticket with no brief at all.
        ticket = self._ticket()
        self._message(ticket, *[f"https://img.example.com/{i}.png" for i in range(MAX_SCREENSHOTS + 3)])
        urls = _screenshot_urls_for(self.team.id, str(ticket.id))
        assert len(urls) == MAX_SCREENSHOTS
        assert TicketBriefSerializer(data={**BASE, "screenshot_urls": urls}).is_valid()

    def test_another_team_s_messages_never_reach_this_ticket_s_brief(self) -> None:
        # item_id is a bare string rather than a foreign key, so the team filter is the only
        # thing scoping this read.
        ticket = self._ticket()
        other_team = Team.objects.create(organization=self.organization, name="Other")
        Comment.objects.create(
            team=other_team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="",
            rich_content={
                "type": "doc",
                "content": [{"type": "image", "attrs": {"src": "https://img.example.com/x.png"}}],
            },
        )
        assert _screenshot_urls_for(self.team.id, str(ticket.id)) == []
