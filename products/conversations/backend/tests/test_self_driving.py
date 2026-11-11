from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import ActivityLog, Organization, Team
from posthog.models.comment import Comment

from products.conversations.backend import ai_gates
from products.conversations.backend.facade.api import escalates_directly, get_ticket_for_agent
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.self_driving import (
    note_text,
    on_agent_run_result,
    on_fix_run_ended,
    ticket_entity,
    triage_patch,
)
from products.conversations.backend.temporal.coordinator import EligibleTicket, _collect_eligible
from products.signals.backend.facade.agent_runs import (
    AgentEntity,
    AgentRunOutcome,
    AgentRunResult,
    Attached,
    AttachedReport,
    AttachedRun,
    ImplementationState,
    ReportImplementation,
)
from products.signals.backend.facade.testing import agent_runs_startable

FLAG_SERVICE = "products.conversations.backend.ai_gates.posthoganalytics.feature_enabled"
BOTH_FLAGS = frozenset({ai_gates.MASTER_FLAG, ai_gates.SELF_DRIVING_ESCALATION_FLAG})
REPORT_ID = "019f9373-1e60-0000-3928-d8b21e6e8cc0"
T0 = datetime(2026, 3, 2, 12, tzinfo=UTC)


def _flags(enabled: frozenset[str]) -> Any:
    return patch(FLAG_SERVICE, side_effect=lambda flag, *_args, **_kwargs: flag in enabled)


def _report(*, run_active: bool = False, report_id: str = REPORT_ID) -> AttachedReport:
    return AttachedReport(
        report_id=report_id,
        relation="created",
        status="ready",
        implementation=ReportImplementation(state=ImplementationState.STARTED, pr_url=None, run_active=run_active),
    )


def _result(
    ticket_id: str = "ticket-1",
    *,
    team_id: int = 1,
    outcome: AgentRunOutcome = AgentRunOutcome.REPORTS,
    output: dict[str, Any] | None = None,
    reports: tuple[AttachedReport, ...] = (),
    next_pass_queued: bool = False,
) -> AgentRunResult:
    return AgentRunResult(
        run_id="run-1",
        team_id=team_id,
        agent="research",
        entity=ticket_entity(ticket_id),
        pass_number=1,
        outcome=outcome,
        reason_code=None,
        next_pass_queued=next_pass_queued,
        reports=reports,
        output=output,
    )


class TestEscalatesDirectlyGates(SimpleTestCase):
    @parameterized.expand(
        [
            ("every gate passes", {}, True),
            ("the escalation flag is off", {"flags": frozenset({ai_gates.MASTER_FLAG})}, False),
            ("the Support AI flag is off", {"flags": frozenset({ai_gates.SELF_DRIVING_ESCALATION_FLAG})}, False),
            ("AI suggestions are off", {"ai_suggestions_enabled": False}, False),
            ("the organization has not approved AI data processing", {"approved": False}, False),
            ("a child environment", {"parent_team_id": 7}, False),
        ]
    )
    def test_a_project_escalates_directly_only_when_every_gate_passes(
        self, _name: str, overrides: dict[str, Any], expected: bool
    ) -> None:
        team = Team(
            id=1,
            parent_team_id=overrides.get("parent_team_id"),
            organization=Organization(is_ai_data_processing_approved=overrides.get("approved", True)),
            conversations_settings={"ai_suggestions_enabled": overrides.get("ai_suggestions_enabled", True)},
        )

        with _flags(overrides.get("flags", BOTH_FLAGS)):
            assert ai_gates.escalates_directly(team) is expected

    def test_a_flag_service_error_reads_as_not_escalating(self) -> None:
        team = Team(
            id=1,
            organization=Organization(is_ai_data_processing_approved=True),
            conversations_settings={"ai_suggestions_enabled": True},
        )

        with patch(FLAG_SERVICE, side_effect=RuntimeError("flag service down")):
            assert ai_gates.escalates_directly(team) is False


class TestTriageFromAgentRun(SimpleTestCase):
    @parameterized.expand(
        [
            ("blocked", AgentRunOutcome.BLOCKED, {}, "blocked_unsafe", None),
            ("failed", AgentRunOutcome.FAILED, {}, "escalated_no_reply", None),
            ("needs input", AgentRunOutcome.NEEDS_INPUT, {}, "suggested_clarification", "blocked_on_customer"),
            ("a report", AgentRunOutcome.REPORTS, {"suggested_reply": "Hi"}, "escalated_with_findings", None),
            (
                "nothing to act on",
                AgentRunOutcome.NOT_ACTIONABLE,
                {"ticket_type": "unactionable"},
                "skipped_unactionable",
                None,
            ),
            ("an answer", AgentRunOutcome.NOT_ACTIONABLE, {"suggested_reply": "Hi"}, "suggested", None),
            ("notes only", AgentRunOutcome.NOT_ACTIONABLE, {}, "escalated_with_findings", None),
        ]
    )
    def test_a_pass_maps_to_a_triage_result_the_ticket_page_knows(
        self, _name: str, outcome: AgentRunOutcome, output: dict[str, Any], result: str, verdict: str | None
    ) -> None:
        patch_ = triage_patch(_result(outcome=outcome, output=output))

        assert (patch_["status"], patch_["result"], patch_.get("verdict")) == ("done", result, verdict)

    @parameterized.expand(
        [
            (
                "the link is added",
                "Looks like a bug in exports.",
                "Looks like a bug in exports.\n\n**Suggested reply**\n\nWe are looking into it.\n\n"
                f"Report: http://localhost:8010/project/1/inbox/reports/{REPORT_ID}?link_source=support",
            ),
            (
                "the note already links the report",
                f"Bug. See /project/1/inbox/reports/{REPORT_ID}",
                f"Bug. See /project/1/inbox/reports/{REPORT_ID}\n\n**Suggested reply**\n\nWe are looking into it.",
            ),
        ]
    )
    def test_the_private_note_ends_with_one_link_to_each_report(self, _name: str, note: str, expected: str) -> None:
        output = {"private_note": note, "suggested_reply": "We are looking into it."}

        with self.settings(SITE_URL="http://localhost:8010"):
            assert note_text(_result(output=output, reports=(_report(),))) == expected

    def test_a_pass_with_no_note_posts_nothing(self) -> None:
        assert note_text(_result(output={"summary": "No note."}, reports=(_report(),))) is None


@patch("products.conversations.backend.events.capture_internal")
class TestSelfDrivingTicketLane(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.team.conversations_settings = {"ai_suggestions_enabled": True}
        self.team.save(update_fields=["conversations_settings"])

    def _ticket(self, *, status: str = Status.NEW, team: Team | None = None, **fields: Any) -> Ticket:
        ticket = Ticket.objects.create_with_number(
            team=team or self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="s",
            distinct_id="person-1",
            **fields,
        )
        Ticket.objects.filter(id=ticket.id).update(status=status)
        ticket.refresh_from_db()
        return ticket

    def _tick(self) -> list[EligibleTicket]:
        # The agent's workflow starts when the hand-over commits, which a test transaction never does.
        with self.captureOnCommitCallbacks(execute=True):
            return _collect_eligible()

    def _comment(self, ticket: Ticket, content: str, *, author: str = "customer", private: bool = False) -> None:
        Comment.objects.create(
            team_id=ticket.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            item_context={"author_type": author, "is_private": private},
        )

    @parameterized.expand(
        [
            ("a flagged project sends a new ticket to the agent", True, Status.NEW, [], "agent"),
            ("an unflagged project keeps the reply workflow", False, Status.NEW, [], "reply workflow"),
            (
                "the agent reads a message that follows its own note on an escalated ticket",
                True,
                Status.ESCALATED,
                [("AI", True), ("customer", False)],
                "agent",
            ),
            ("the reply workflow never drafts on an escalated ticket", False, Status.ESCALATED, [], "nobody"),
            ("a teammate who replied in public has the ticket", True, Status.OPEN, [("support", False)], "nobody"),
        ]
    )
    def test_the_coordinator_routes_a_settled_ticket(
        self,
        _capture: MagicMock,
        _name: str,
        flagged: bool,
        status: str,
        later_comments: list[tuple[str, bool]],
        expected: str,
    ) -> None:
        with time_machine.travel(T0, tick=False) as clock:
            ticket = self._ticket(status=status)
            self._comment(ticket, "The export never finishes.")
            for author, private in later_comments:
                clock.shift(timedelta(seconds=10))
                self._comment(ticket, "A follow-up.", author=author, private=private)
            clock.shift(timedelta(minutes=3))

            with (
                _flags(BOTH_FLAGS if flagged else frozenset({ai_gates.MASTER_FLAG})),
                agent_runs_startable(self.team, product="conversations", type="ticket") as started,
            ):
                eligible = self._tick()
                # The ticket stays in the scan window, so the next tick asks again.
                eligible_next_tick = self._tick()

        ticket.refresh_from_db()
        for_reply_workflow = [EligibleTicket(team_id=self.team.id, ticket_id=str(ticket.id))]
        assert eligible == eligible_next_tick == (for_reply_workflow if expected == "reply workflow" else [])
        assert len(started) == (1 if expected == "agent" else 0)
        if expected == "agent":
            assert (ticket.ai_triage["status"], ticket.ai_triage["run_id"]) == ("in_progress", started[0])

    def test_the_cap_bounds_new_agent_runs_and_a_ticket_the_agent_already_reads_does_not_use_it(
        self, _capture: MagicMock
    ) -> None:
        with (
            time_machine.travel(T0, tick=False) as clock,
            _flags(BOTH_FLAGS),
            agent_runs_startable(self.team, product="conversations", type="ticket") as started,
            patch("products.conversations.backend.temporal.coordinator.MAX_TICKETS_PER_TEAM_PER_RUN", 1),
        ):
            for message in ("The export never finishes.", "I cannot log in."):
                self._comment(self._ticket(), message)
            clock.shift(timedelta(minutes=2))

            self._tick()
            started_by_the_first_tick = len(started)
            self._tick()

        assert (started_by_the_first_tick, len(started)) == (1, 2)

    def test_a_child_environment_of_a_flagged_organization_keeps_the_reply_workflow(self, _capture: MagicMock) -> None:
        child = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="Child",
            conversations_settings={"ai_suggestions_enabled": True},
        )
        with time_machine.travel(T0, tick=False) as clock:
            ticket = self._ticket(team=child)
            self._comment(ticket, "The export never finishes.")
            clock.shift(timedelta(minutes=2))

            with (
                _flags(BOTH_FLAGS),
                agent_runs_startable(self.team, product="conversations", type="ticket") as started,
            ):
                eligible = self._tick()

        assert eligible == [EligibleTicket(team_id=child.id, ticket_id=str(ticket.id))]
        assert started == []

    def test_a_ticket_that_cannot_be_handed_over_does_not_fail_the_tick(self, _capture: MagicMock) -> None:
        with time_machine.travel(T0, tick=False) as clock:
            ticket = self._ticket()
            self._comment(ticket, "The export never finishes.")
            clock.shift(timedelta(minutes=2))

            with (
                _flags(BOTH_FLAGS),
                patch(
                    "products.conversations.backend.self_driving.request_agent_run",
                    side_effect=RuntimeError("database is down"),
                ),
            ):
                assert self._tick() == []

    def test_the_facade_reads_the_gates_of_the_project(self, _capture: MagicMock) -> None:
        with _flags(BOTH_FLAGS):
            assert escalates_directly(self.team.id) is True
            assert escalates_directly(self.team.id + 1000) is False

    def test_the_agent_gets_the_public_thread_and_a_hash_that_follows_it(self, _capture: MagicMock) -> None:
        ticket = self._ticket(email_subject="Export fails")
        self._comment(ticket, "The export never finishes.")
        self._comment(ticket, "Which export?", author="support")
        before = get_ticket_for_agent(self.team.id, str(ticket.id))
        self._comment(ticket, "Customer is on the legacy plan.", author="support", private=True)
        after_private_note = get_ticket_for_agent(self.team.id, str(ticket.id))
        self._comment(ticket, "The CSV one.")
        after_public_message = get_ticket_for_agent(self.team.id, str(ticket.id))

        assert before is not None and after_private_note is not None and after_public_message is not None
        assert (before.subject, [(m.author_type, m.content) for m in after_private_note.messages]) == (
            "Export fails",
            [("customer", "The export never finishes."), ("support", "Which export?")],
        )
        assert after_private_note.content_hash == before.content_hash
        assert after_public_message.content_hash != before.content_hash
        assert get_ticket_for_agent(self.team.id + 1000, str(ticket.id)) is None

    def _notes(self, ticket: Ticket) -> list[str]:
        return list(
            Comment.objects.filter(
                team=self.team, item_id=str(ticket.id), item_context__author_type="AI", item_context__is_private=True
            ).values_list("content", flat=True)
        )

    def test_a_finished_pass_posts_one_private_note_and_reopens_the_ticket(self, capture: MagicMock) -> None:
        ticket = self._ticket(status=Status.ESCALATED)
        result = _result(
            str(ticket.id),
            team_id=self.team.id,
            output={
                "ticket_type": "bug",
                "summary": "Exports time out for large projects.",
                "private_note": "Looks like a bug in exports.",
                "knowledge_gap_topics": ["export limits"],
            },
            reports=(_report(),),
        )

        on_agent_run_result(result)
        # Self-driving delivers a result again when its own step is retried.
        on_agent_run_result(result)

        ticket.refresh_from_db()
        notes = self._notes(ticket)
        assert len(notes) == 1 and notes[0].startswith("Looks like a bug in exports.\n\nReport: ")
        assert ticket.status == Status.OPEN
        triage = ticket.ai_triage
        assert (triage["status"], triage["result"], triage["ticket_type"], triage["missing"]) == (
            "done",
            "escalated_with_findings",
            "bug",
            ["export limits"],
        )
        status_events = [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs["event_name"] == "$conversation_ticket_status_changed"
        ]
        assert [(event["old_status"], event["new_status"]) for event in status_events] == [("escalated", "open")]
        assert ActivityLog.objects.filter(team_id=self.team.id, scope="Ticket", item_id=str(ticket.id)).count() == 1

    @parameterized.expand(
        [
            ("a status a teammate set is kept", Status.PENDING, {}, Status.PENDING, "done"),
            (
                "a waiting pass keeps the ticket escalated",
                Status.ESCALATED,
                {"next": True},
                Status.ESCALATED,
                "in_progress",
            ),
            (
                "a running fix keeps the ticket escalated when the project asked for that",
                Status.ESCALATED,
                {"covers_fix_run": True, "run_active": True},
                Status.ESCALATED,
                "done",
            ),
            (
                "a running fix does not hold the ticket by default",
                Status.ESCALATED,
                {"run_active": True},
                Status.OPEN,
                "done",
            ),
            (
                "a fix run that already ended does not hold the ticket",
                Status.ESCALATED,
                {"covers_fix_run": True},
                Status.OPEN,
                "done",
            ),
        ]
    )
    def test_the_status_after_a_pass(
        self,
        _capture: MagicMock,
        _name: str,
        status: str,
        case: dict[str, bool],
        expected_status: str,
        expected_triage_status: str,
    ) -> None:
        self.team.conversations_settings = {
            "ai_suggestions_enabled": True,
            "ai_escalation_covers_fix_run": case.get("covers_fix_run", False),
        }
        self.team.save(update_fields=["conversations_settings"])
        ticket = self._ticket(status=status)

        on_agent_run_result(
            _result(
                str(ticket.id),
                team_id=self.team.id,
                output={"private_note": "A note."},
                reports=(_report(run_active=case.get("run_active", False)),),
                next_pass_queued=case.get("next", False),
            )
        )

        ticket.refresh_from_db()
        assert (ticket.status, ticket.ai_triage["status"]) == (expected_status, expected_triage_status)

    @parameterized.expand(
        [
            ("nothing else is running", Status.ESCALATED, None, False, Status.OPEN),
            ("the agent still reads the ticket", Status.ESCALATED, "running", False, Status.ESCALATED),
            ("another fix run is still running", Status.ESCALATED, None, True, Status.ESCALATED),
            ("a teammate already moved the ticket", Status.RESOLVED, None, False, Status.RESOLVED),
        ]
    )
    def test_the_status_after_a_fix_run_ended(
        self,
        _capture: MagicMock,
        _name: str,
        status: str,
        pass_status: str | None,
        other_fix_running: bool,
        expected_status: str,
    ) -> None:
        ticket = self._ticket(status=status)
        attached = Attached(
            run=AttachedRun(
                run_id="run-1",
                pass_number=1,
                status=pass_status or "done",
                outcome="reports",
                reason_code=None,
                updated_at=T0,
            ),
            reports=(_report(), _report(run_active=other_fix_running, report_id="another-report")),
        )

        with patch("products.conversations.backend.self_driving.get_attached", return_value={str(ticket.id): attached}):
            on_fix_run_ended(
                self.team.id, AgentEntity(product="conversations", type="ticket", id=str(ticket.id)), REPORT_ID
            )

        ticket.refresh_from_db()
        assert ticket.status == expected_status
