from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio import workflow

from products.conversations.backend.temporal.coordinator import (
    CoordinatorInput,
    EligibleTicket,
    SupportReplyCoordinatorWorkflow,
    _collect_eligible,
    _is_master_flag_enabled,
    support_collect_eligible_tickets_activity,
)

TEST_TEAM_UUID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEST_ORG_UUID = uuid.UUID("22222222-2222-4222-8222-222222222222")

COORD_MODULE = "products.conversations.backend.temporal.coordinator"


@workflow.defn(name="support-reply-pipeline")
class _StubChildWorkflow:
    """Stands in for SupportReplyWorkflow (same registered name) so the coordinator's child
    dispatch resolves to a no-op instead of running the real pipeline."""

    @workflow.run
    async def run(self, _input) -> str:
        return "persisted"


def _make_ticket(
    team_id: int = 1,
    ticket_id: str | None = None,
    *,
    ai_suggestions_enabled: bool = True,
    ai_data_processing_approved: bool = True,
    has_ready_sources: bool = True,
    has_ai_note: bool = False,
    has_team_reply: bool = False,
    channel_source: str = "widget",
    ai_resolution_channels: list[str] | None = None,
    created_minutes_ago: int = 10,
):
    ticket_id = ticket_id or str(uuid.uuid4())
    org = MagicMock()
    org.is_ai_data_processing_approved = ai_data_processing_approved
    team = MagicMock()
    team.id = team_id
    team.uuid = TEST_TEAM_UUID
    team.organization_id = TEST_ORG_UUID
    team.organization = org
    settings: dict = {"ai_suggestions_enabled": ai_suggestions_enabled}
    if ai_resolution_channels is not None:
        settings["ai_resolution_channels"] = ai_resolution_channels
    team.conversations_settings = settings
    ticket = MagicMock()
    ticket.id = uuid.UUID(ticket_id)
    ticket.team = team
    ticket.channel_source = channel_source
    # Default well past the settle window so eligibility tests aren't gated on debounce.
    ticket.created_at = timezone.now() - timedelta(minutes=created_minutes_ago)
    return ticket, ticket_id, team


class TestMasterFlagEnabled:
    @patch(f"{COORD_MODULE}.posthoganalytics.feature_enabled", return_value=True)
    def test_evaluates_flag_with_team_uuid_and_groups(self, mock_feature_enabled):
        team = MagicMock()
        team.id = 2
        team.uuid = TEST_TEAM_UUID
        team.organization_id = TEST_ORG_UUID

        assert _is_master_flag_enabled(team) is True
        mock_feature_enabled.assert_called_once_with(
            "product-support-ai-suggestion",
            str(TEST_TEAM_UUID),
            groups={
                "organization": str(TEST_ORG_UUID),
                "project": "2",
            },
            group_properties={
                "organization": {"id": str(TEST_ORG_UUID)},
                "project": {"id": "2", "uuid": str(TEST_TEAM_UUID)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )


class TestCollectEligible:
    @parameterized.expand(
        [
            ("master_flag_off", {"master_flag": False}),
            ("ai_suggestions_disabled", {"ai_suggestions_enabled": False}),
            ("ai_data_processing_not_approved", {"ai_data_processing_approved": False}),
            ("no_ready_sources", {"has_ready_sources": False}),
            ("has_ai_note", {"has_ai_note": True}),
            ("has_team_reply", {"has_team_reply": True}),
            ("channel_not_allowed", {"ai_resolution_channels": ["email"], "channel_source": "widget"}),
        ]
    )
    # Force the BK-readiness gate on (production default MIN_READY_BK_SOURCES=0 skips it) so the
    # no_ready_sources case actually exercises the check. A literal patch value injects no arg.
    @patch(f"{COORD_MODULE}.MIN_READY_BK_SOURCES", 1)
    @patch(f"{COORD_MODULE}.has_ready_sources")
    @patch(f"{COORD_MODULE}.Comment")
    @patch(f"{COORD_MODULE}.Ticket")
    @patch(f"{COORD_MODULE}._is_master_flag_enabled")
    def test_gate_blocks(
        self,
        _name,
        overrides,
        mock_master_flag,
        mock_ticket_model,
        mock_comment_model,
        mock_has_ready,
    ):
        master_flag = overrides.get("master_flag", True)
        ai_suggestions_enabled = overrides.get("ai_suggestions_enabled", True)
        ai_data_processing_approved = overrides.get("ai_data_processing_approved", True)
        has_ready = overrides.get("has_ready_sources", True)
        has_ai = overrides.get("has_ai_note", False)
        has_team_reply = overrides.get("has_team_reply", False)

        ticket, ticket_id, team = _make_ticket(
            ai_suggestions_enabled=ai_suggestions_enabled,
            ai_data_processing_approved=ai_data_processing_approved,
            has_ready_sources=has_ready,
            channel_source=overrides.get("channel_source", "widget"),
            ai_resolution_channels=overrides.get("ai_resolution_channels"),
        )

        mock_master_flag.return_value = master_flag
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]
        mock_has_ready.return_value = has_ready

        # One query per team: .filter().values_list("item_id", author_type, created_at) rows.
        now = timezone.now()
        rows: list[tuple[str, str, object]] = []
        if has_ai:
            rows.append((ticket_id, "AI", now))
        if has_team_reply:
            rows.append((ticket_id, "support", now))
        mock_comment_model.objects.filter.return_value.values_list.return_value = rows

        result = _collect_eligible()
        assert result == []

    @patch(f"{COORD_MODULE}.has_ready_sources", return_value=True)
    @patch(f"{COORD_MODULE}.Comment")
    @patch(f"{COORD_MODULE}.Ticket")
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_eligible_ticket_passes_all_gates(
        self,
        mock_master_flag,
        mock_ticket_model,
        mock_comment_model,
        mock_has_ready,
    ):
        ticket, ticket_id, team = _make_ticket()
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]

        # No comments → not engaged (only customer messages would be, and there are none).
        mock_comment_model.objects.filter.return_value.values_list.return_value = []

        result = _collect_eligible()
        assert len(result) == 1
        assert result[0].team_id == team.id
        assert result[0].ticket_id == ticket_id

    @parameterized.expand(
        [
            ("channel_in_allowed_list", ["widget"], "widget"),
            ("null_allows_all", None, "slack"),
        ]
    )
    @patch(f"{COORD_MODULE}.has_ready_sources", return_value=True)
    @patch(f"{COORD_MODULE}.Comment")
    @patch(f"{COORD_MODULE}.Ticket")
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_channel_gate_passes(
        self,
        _name,
        ai_resolution_channels,
        channel_source,
        mock_master_flag,
        mock_ticket_model,
        mock_comment_model,
        mock_has_ready,
    ):
        ticket, ticket_id, team = _make_ticket(
            channel_source=channel_source,
            ai_resolution_channels=ai_resolution_channels,
        )
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]
        mock_comment_model.objects.filter.return_value.values_list.return_value = []

        result = _collect_eligible()
        assert len(result) == 1

    @patch(f"{COORD_MODULE}.has_ready_sources", return_value=True)
    @patch(f"{COORD_MODULE}.Comment")
    @patch(f"{COORD_MODULE}.Ticket")
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_dedupe_skips_ticket_with_ai_note(
        self,
        mock_master_flag,
        mock_ticket_model,
        mock_comment_model,
        mock_has_ready,
    ):
        ticket, ticket_id, team = _make_ticket()
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]

        # AI note exists → engaged → skipped.
        mock_comment_model.objects.filter.return_value.values_list.return_value = [(ticket_id, "AI", timezone.now())]

        result = _collect_eligible()
        assert result == []

    @parameterized.expand(
        [
            # (name, ticket_created_min_ago, latest_customer_msg_min_ago | None, expected_eligible)
            ("fresh_ticket_no_comments_still_settling", 0, None, False),
            ("old_ticket_no_comments_settled", 30, None, True),
            ("recent_customer_followup_still_settling", 30, 0, False),
            ("old_customer_followup_settled", 30, 30, True),
        ]
    )
    @patch(f"{COORD_MODULE}.has_ready_sources", return_value=True)
    @patch(f"{COORD_MODULE}.Comment")
    @patch(f"{COORD_MODULE}.Ticket")
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_settle_window_gates_until_customer_goes_quiet(
        self,
        _name,
        created_min_ago,
        last_msg_min_ago,
        expected_eligible,
        mock_master_flag,
        mock_ticket_model,
        mock_comment_model,
        mock_has_ready,
    ):
        # Guards the debounce: a ticket whose customer just sent a message (or was just created)
        # must not be drafted until they've gone quiet for TICKET_SETTLE_MINUTES, so follow-up
        # messages get folded into the same draft. Drop the settle gate and the two "still_settling"
        # cases start returning the ticket immediately.
        ticket, ticket_id, team = _make_ticket(created_minutes_ago=created_min_ago)
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]

        rows: list[tuple[str, str, object]] = []
        if last_msg_min_ago is not None:
            rows.append((ticket_id, "customer", timezone.now() - timedelta(minutes=last_msg_min_ago)))
        mock_comment_model.objects.filter.return_value.values_list.return_value = rows

        result = _collect_eligible()
        assert (len(result) == 1) == expected_eligible


class TestCollectEligibleScanWindow:
    @parameterized.expand(
        [
            # (name, last_customer_msg_min_ago, expected_collected)
            # Ticket is always created far outside the lookback window; eligibility must follow the
            # last message, not creation time.
            ("recent_message_old_ticket_collected", 3, True),
            ("quiet_too_long_dropped", 30, False),
        ]
    )
    @pytest.mark.django_db
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_scan_keys_on_last_message_not_created_at(
        self,
        _name,
        last_msg_min_ago,
        expected_collected,
        mock_master_flag,
    ):
        # Models imported lazily: this module defines a @workflow.defn stub, so Temporal's sandbox
        # re-imports the whole file during validation and top-level Django ORM imports break it.
        from posthog.models import Organization, Team
        from posthog.models.comment import Comment

        from products.conversations.backend.models.ticket import Ticket as TicketModel

        # Guards the scan dimension: a ticket created long ago (well outside TICKET_LOOKBACK_MINUTES)
        # but with a recent customer message must still be collected — revert the queryset to
        # `created_at`-only and this 60-min-old ticket is silently dropped despite a fresh message.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(
            organization=org, name="Team", conversations_settings={"ai_suggestions_enabled": True}
        )
        ticket = TicketModel.objects.create_with_number(
            team=team,
            widget_session_id="aabbccdd-0000-0000-0000-000000000001",
            distinct_id="u1",
            channel_source="widget",
        )
        msg_at = timezone.now() - timedelta(minutes=last_msg_min_ago)
        # created_at is auto_now_add and last_message_at is set by a post-commit signal that doesn't
        # fire here, so pin both directly to decouple creation time from last-activity time.
        TicketModel.objects.filter(id=ticket.id).update(
            created_at=timezone.now() - timedelta(minutes=60), last_message_at=msg_at
        )
        comment = Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="hi",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.filter(id=comment.id).update(created_at=msg_at)

        result = _collect_eligible()
        assert [t.ticket_id for t in result] == ([str(ticket.id)] if expected_collected else [])


class TestCollectEligibleStatus:
    @parameterized.expand(
        [
            ("new", "new", True),
            ("open", "open", True),
            ("pending", "pending", False),
            ("on_hold", "on_hold", False),
            ("resolved", "resolved", False),
        ]
    )
    @pytest.mark.django_db
    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    def test_only_new_and_open_tickets_collected(
        self,
        _name,
        ticket_status,
        expected_collected,
        mock_master_flag,
    ):
        from posthog.models import Organization, Team

        from products.conversations.backend.models.ticket import Ticket as TicketModel

        org = Organization.objects.create(name="Org")
        team = Team.objects.create(
            organization=org, name="Team", conversations_settings={"ai_suggestions_enabled": True}
        )
        ticket = TicketModel.objects.create_with_number(
            team=team,
            widget_session_id=f"aabbccdd-0000-0000-0000-{uuid.uuid4().hex[:12]}",
            distinct_id="u1",
            channel_source="widget",
            status=ticket_status,
        )
        settled_at = timezone.now() - timedelta(minutes=3)
        TicketModel.objects.filter(id=ticket.id).update(
            created_at=settled_at,
            last_message_at=settled_at,
        )

        result = _collect_eligible()
        assert [t.ticket_id for t in result] == ([str(ticket.id)] if expected_collected else [])


class TestCoordinatorWorkflow:
    @pytest.mark.asyncio
    @patch(f"{COORD_MODULE}._collect_eligible")
    async def test_no_eligible_tickets(self, mock_collect):
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        mock_collect.return_value = []

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[SupportReplyCoordinatorWorkflow],
                activities=[support_collect_eligible_tickets_activity],
            ):
                result = await env.client.execute_workflow(
                    SupportReplyCoordinatorWorkflow.run,
                    CoordinatorInput(),
                    id="test-coordinator",
                    task_queue="test-queue",
                )

        assert result.eligible_count == 0
        assert result.started_count == 0
        assert result.skipped_count == 0

    @pytest.mark.asyncio
    @patch(f"{COORD_MODULE}._collect_eligible")
    async def test_fans_out_eligible_tickets(self, mock_collect):
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        mock_collect.return_value = [
            EligibleTicket(team_id=1, ticket_id="ticket-a"),
            EligibleTicket(team_id=1, ticket_id="ticket-b"),
        ]

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[SupportReplyCoordinatorWorkflow, _StubChildWorkflow],
                activities=[support_collect_eligible_tickets_activity],
            ):
                result = await env.client.execute_workflow(
                    SupportReplyCoordinatorWorkflow.run,
                    CoordinatorInput(),
                    id="test-coordinator-fanout",
                    task_queue="test-queue",
                )

        assert result.eligible_count == 2
        assert result.started_count == 2
        assert result.skipped_count == 0

    @pytest.mark.asyncio
    @patch(f"{COORD_MODULE}._collect_eligible")
    async def test_skips_duplicate_child(self, mock_collect):
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        # Two entries for the same ticket → same deterministic child id → the second dispatch
        # hits WorkflowAlreadyStartedError and is counted as skipped, not started.
        mock_collect.return_value = [
            EligibleTicket(team_id=1, ticket_id="dup"),
            EligibleTicket(team_id=1, ticket_id="dup"),
        ]

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[SupportReplyCoordinatorWorkflow, _StubChildWorkflow],
                activities=[support_collect_eligible_tickets_activity],
            ):
                result = await env.client.execute_workflow(
                    SupportReplyCoordinatorWorkflow.run,
                    CoordinatorInput(),
                    id="test-coordinator-dedupe",
                    task_queue="test-queue",
                )

        assert result.eligible_count == 2
        assert result.started_count == 1
        assert result.skipped_count == 1
