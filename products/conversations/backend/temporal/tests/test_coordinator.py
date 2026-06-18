from __future__ import annotations

import uuid

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.temporal.coordinator import (
    CoordinatorInput,
    SupportReplyCoordinatorWorkflow,
    _collect_eligible,
    collect_eligible_tickets_activity,
)

COORD_MODULE = "products.conversations.backend.temporal.coordinator"


def _make_ticket(
    team_id: int = 1,
    ticket_id: str | None = None,
    *,
    ai_suggestions_enabled: bool = True,
    ai_data_processing_approved: bool = True,
    has_ready_sources: bool = True,
    has_ai_note: bool = False,
    has_team_reply: bool = False,
):
    ticket_id = ticket_id or str(uuid.uuid4())
    org = MagicMock()
    org.is_ai_data_processing_approved = ai_data_processing_approved
    team = MagicMock()
    team.id = team_id
    team.organization = org
    team.conversations_settings = {"ai_suggestions_enabled": ai_suggestions_enabled}
    ticket = MagicMock()
    ticket.id = uuid.UUID(ticket_id)
    ticket.team = team
    return ticket, ticket_id, team


class TestCollectEligible:
    @parameterized.expand(
        [
            ("master_flag_off", {"master_flag": False}),
            ("ai_suggestions_disabled", {"ai_suggestions_enabled": False}),
            ("ai_data_processing_not_approved", {"ai_data_processing_approved": False}),
            ("no_ready_sources", {"has_ready_sources": False}),
            ("has_ai_note", {"has_ai_note": True}),
            ("has_team_reply", {"has_team_reply": True}),
            ("rollout_off", {"rollout": False}),
        ]
    )
    @patch(f"{COORD_MODULE}._is_rollout_enabled")
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
        mock_rollout,
    ):
        master_flag = overrides.get("master_flag", True)
        ai_suggestions_enabled = overrides.get("ai_suggestions_enabled", True)
        ai_data_processing_approved = overrides.get("ai_data_processing_approved", True)
        has_ready = overrides.get("has_ready_sources", True)
        has_ai = overrides.get("has_ai_note", False)
        has_team_reply = overrides.get("has_team_reply", False)
        rollout = overrides.get("rollout", True)

        ticket, ticket_id, team = _make_ticket(
            ai_suggestions_enabled=ai_suggestions_enabled,
            ai_data_processing_approved=ai_data_processing_approved,
            has_ready_sources=has_ready,
        )

        mock_master_flag.return_value = master_flag
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]
        mock_has_ready.return_value = has_ready

        # AI note check
        mock_ai_qs = MagicMock()
        mock_ai_qs.exists.return_value = has_ai
        # Team reply check: .filter().exclude().exclude().exists() — exclude returns self.
        mock_team_chain = MagicMock()
        mock_team_chain.exclude.return_value = mock_team_chain
        mock_team_chain.exists.return_value = has_team_reply
        mock_comment_model.objects.filter.side_effect = [mock_ai_qs, mock_team_chain]

        mock_rollout.return_value = rollout

        result = _collect_eligible()
        assert result == []

    @patch(f"{COORD_MODULE}._is_rollout_enabled", return_value=True)
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
        mock_rollout,
    ):
        ticket, ticket_id, team = _make_ticket()
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]

        # No AI note
        mock_ai_qs = MagicMock()
        mock_ai_qs.exists.return_value = False
        # No team reply — the chain: .filter().exclude().exclude().exists()
        mock_team_chain = MagicMock()
        mock_team_chain.exclude.return_value = mock_team_chain
        mock_team_chain.exists.return_value = False
        mock_comment_model.objects.filter.side_effect = [mock_ai_qs, mock_team_chain]

        result = _collect_eligible()
        assert len(result) == 1
        assert result[0].team_id == team.id
        assert result[0].ticket_id == ticket_id

    @patch(f"{COORD_MODULE}._is_rollout_enabled", return_value=True)
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
        mock_rollout,
    ):
        ticket, ticket_id, team = _make_ticket()
        mock_ticket_model.objects.filter.return_value.select_related.return_value = [ticket]

        # AI note exists
        mock_ai_qs = MagicMock()
        mock_ai_qs.exists.return_value = True
        mock_comment_model.objects.filter.return_value = mock_ai_qs

        result = _collect_eligible()
        assert result == []


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
                activities=[collect_eligible_tickets_activity],
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
