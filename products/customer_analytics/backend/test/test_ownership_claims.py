from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import IntegrityError, OperationalError, transaction
from django.db.models.deletion import RestrictedError
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import ScheduleOverlapPolicy, ScheduleState
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.hogql.errors import QueryError

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic import ownership_claims, relationships
from products.customer_analytics.backend.logic.ownership_claims import DECISION_COLUMNS
from products.customer_analytics.backend.models import (
    AccountRelationship,
    AccountRelationshipControl,
    AccountRelationshipDefinition,
)
from products.customer_analytics.backend.temporal.ownership_claims import (
    OWNERSHIP_CLAIMS_COORDINATOR_EXECUTION_TIMEOUT,
    OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID,
    OWNERSHIP_CLAIMS_INTERVAL,
    OWNERSHIP_CLAIMS_SWEEP_EXECUTION_TIMEOUT,
    OwnershipClaimsCoordinatorInput,
    OwnershipClaimsCoordinatorOutput,
    OwnershipClaimsCoordinatorWorkflow,
    OwnershipClaimsProjects,
    create_ownership_claims_coordinator_schedule,
    ownership_claims_workflow_id,
)
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_saved_query,
    enroll_account,
    saved_query_columns,
)

FENCE = datetime(2026, 1, 1, tzinfo=UTC)
TASK = "example-salesforce-task-17"


class TestOwnershipClaims(BaseTest):
    def setUp(self):
        super().setUp()
        self.ae_definition, self.view = self._claim_bound_definition("Account executive", "ownership_decisions")
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="org-1")
        self.control = enroll_account(self.account, self.ae_definition, controlled_at=FENCE)
        self.human = relationships.Actor.human(self.user)

    def _claim_bound_definition(self, name: str, view_name: str) -> tuple[AccountRelationshipDefinition, Any]:
        view = create_saved_query(team_id=self.team.id, name=view_name, columns=saved_query_columns(DECISION_COLUMNS))
        definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, is_controlled=True, claims_enabled=True, claim_saved_query=view
        )
        return definition, view

    def _decision(self, **overrides) -> contracts.OwnershipClaimDecision:
        base = contracts.OwnershipClaimDecision(
            source_ref=TASK,
            organization_id="org-1",
            region="us",
            assignee_user_id=self.user.id,
            source_assignee_id="example-salesforce-user-17",
            allocated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        return replace(base, **overrides)

    def _release(self, **overrides) -> contracts.OwnershipClaimDecision:
        return self._decision(
            released_at=datetime(2026, 1, 3, tzinfo=UTC), source_releaser_id="example-salesforce-user-99", **overrides
        )

    def _claim(self, **overrides) -> contracts.OwnershipClaimResult:
        return ownership_claims.claim(
            team=self.team, definition=self.ae_definition, decision=self._decision(**overrides)
        )

    def _release_claim(self, **overrides) -> contracts.OwnershipClaimResult:
        return ownership_claims.release(team=self.team, decision=self._release(**overrides))

    def _active_ae(self) -> AccountRelationship | None:
        return (
            AccountRelationship.objects.for_team(self.team.id)
            .filter(account=self.account, definition=self.ae_definition, ended_at__isnull=True)
            .first()
        )

    def _fence(self) -> datetime | None:
        return (
            AccountRelationshipControl.objects.for_team(self.team.id)
            .filter(account=self.account, definition=self.ae_definition)
            .values_list("controlled_at", flat=True)
            .first()
        )

    def _assign_by_human(self, user: User) -> AccountRelationship:
        return relationships.assign(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, user=user, actor=self.human
        )

    def _clear_by_human(self) -> None:
        relationships.end_active(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
        )

    def test_claim_fills_an_empty_managed_role(self):
        result = self._claim()

        assert result.outcome == "accepted"
        holder = self._active_ae()
        assert holder is not None and result.relationship_id == holder.id
        assert (holder.user_id, holder.source, holder.source_ref) == (self.user.id, "salesforce_claim", TASK)
        assert self._fence() == FENCE and result.controlled_at == FENCE
        activity = ActivityLog.objects.get(team_id=self.team.id, scope="Account", activity="role_claimed")
        assert activity.is_system
        assert activity.detail is not None
        assert activity.detail["context"]["source_ref"] == TASK
        assert activity.detail["context"]["source_actor_id"] == "example-salesforce-user-17"

    def test_rereading_an_accepted_task_answers_the_original_decision_after_a_human_clear(self):
        first = self._claim()
        self._clear_by_human()
        fence = self._fence()

        again = self._claim()

        assert (again.outcome, again.relationship_id) == ("already_applied", first.relationship_id)
        assert self._active_ae() is None
        assert self._fence() == fence
        assert AccountRelationship.objects.for_team(self.team.id).filter(source_ref=TASK).count() == 1

    @parameterized.expand(
        [
            ("occupied_by_another_user", "rejected", "role_occupied"),
            ("occupied_by_the_same_user", "rejected", "role_occupied"),
            ("allocated_within_the_skew_allowance", "rejected", "stale_allocation"),
            ("allocated_before_a_human_clear", "rejected", "stale_allocation"),
            ("allocated_in_the_future", "rejected", "future_allocation"),
            ("role_not_managed", "blocked", "role_not_managed"),
            ("unknown_organization", "blocked", "account_not_found"),
            ("region_mismatch", "blocked", "identity_mismatch"),
            ("two_accounts_differ_only_by_case", "blocked", "identity_mismatch"),
            ("assignee_not_a_member", "blocked", "assignee_not_member"),
            ("different_case_is_the_same_identity", "accepted", None),
        ]
    )
    def test_claim_decision_outcome(self, case, outcome, reason):
        overrides: dict[str, Any] = {}
        if case == "occupied_by_another_user":
            self._assign_by_human(self._create_user("other@posthog.com"))
        elif case == "occupied_by_the_same_user":
            self._assign_by_human(self.user)
        elif case == "allocated_within_the_skew_allowance":
            overrides["allocated_at"] = datetime(2026, 1, 1, 0, 4, 59, tzinfo=UTC)
        elif case == "allocated_before_a_human_clear":
            self._clear_by_human()
        elif case == "allocated_in_the_future":
            overrides["allocated_at"] = timezone.now() + timedelta(days=1)
        elif case == "role_not_managed":
            self.control.delete()
        elif case == "unknown_organization":
            overrides["organization_id"] = "org-2"
        elif case == "two_accounts_differ_only_by_case":
            shadow = create_account(team_id=self.team.id, name="Shadow", external_id="ORG-1")
            enroll_account(shadow, self.ae_definition, controlled_at=FENCE)
        elif case == "region_mismatch":
            overrides["region"] = "eu"
        elif case == "assignee_not_a_member":
            overrides["assignee_user_id"] = User.objects.create_user("outsider@example.com", None, "").id
        elif case == "different_case_is_the_same_identity":
            overrides["organization_id"] = "ORG-1"
        holder_before = self._active_ae()
        fence_before = self._fence()

        with override_settings(CLOUD_DEPLOYMENT="US"):
            result = self._claim(**overrides)

        assert (result.outcome, result.reason) == (outcome, reason)
        if outcome == "accepted":
            return
        assert self._active_ae() == holder_before
        assert self._fence() == fence_before
        assert not AccountRelationship.objects.for_team(self.team.id).filter(source="salesforce_claim").exists()

    def test_release_ends_only_the_relationship_the_task_claimed(self):
        claimed = self._claim()
        fence_after_claim = self._fence()

        released = self._release_claim()

        assert (released.outcome, released.relationship_id) == ("cleared", claimed.relationship_id)
        assert self._active_ae() is None
        fence = self._fence()
        assert fence == fence_after_claim == FENCE
        activity = ActivityLog.objects.get(team_id=self.team.id, activity="role_released")
        assert activity.detail is not None
        assert activity.detail["context"]["source_actor_id"] == "example-salesforce-user-99"
        assert activity.detail["context"]["source_decided_at"] == "2026-01-03T00:00:00+00:00"

        repeated = self._release_claim()

        assert repeated.outcome == "not_held"
        assert self._fence() == fence
        assert ActivityLog.objects.filter(team_id=self.team.id, activity="role_released").count() == 1

    def test_a_task_allocated_after_a_release_is_accepted_when_the_release_was_processed_later(self):
        self._claim()
        self._release_claim()

        result = self._claim(source_ref="task-2", allocated_at=datetime(2026, 1, 3, 0, 10, tzinfo=UTC))

        assert result.outcome == "accepted"
        holder = self._active_ae()
        assert holder is not None and holder.source_ref == "task-2"

    @parameterized.expand(["after_a_human_transfer", "after_a_human_clear"])
    def test_release_after_a_human_decision_is_not_held(self, decision):
        self._claim()
        if decision == "after_a_human_transfer":
            self._assign_by_human(self._create_user("successor@posthog.com"))
        else:
            self._clear_by_human()
        holder_before = self._active_ae()
        fence_before = self._fence()

        released = self._release_claim()

        assert released.outcome == "not_held"
        assert self._active_ae() == holder_before
        assert self._fence() == fence_before

    def test_release_ends_its_own_row_when_another_definition_takes_claims_too(self):
        first = self._claim()
        csm_definition, _ = self._claim_bound_definition("CSM", "csm_decisions")
        enroll_account(self.account, csm_definition, controlled_at=FENCE)
        second = ownership_claims.claim(
            team=self.team, definition=csm_definition, decision=self._decision(source_ref="task-2")
        )

        released = self._release_claim()

        assert (released.outcome, released.relationship_id) == ("cleared", first.relationship_id)
        assert self._active_ae() is None
        csm_holder = AccountRelationship.objects.for_team(self.team.id).get(
            definition=csm_definition, ended_at__isnull=True
        )
        assert csm_holder.id == second.relationship_id
        fences = AccountRelationshipControl.objects.for_team(self.team.id).filter(account=self.account)
        assert set(fences.values_list("controlled_at", flat=True)) == {FENCE}

    def test_a_source_reference_is_unique_per_team_and_source_in_the_database(self):
        self._claim()

        AccountRelationship.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            account=self.account,
            definition=self.ae_definition,
            source="workflow",
            source_ref=TASK,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountRelationship.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                account=self.account,
                definition=self.ae_definition,
                source="salesforce_claim",
                source_ref=TASK,
            )

    def test_release_of_an_undelivered_claim_is_not_held(self):
        released = self._release_claim()

        assert (released.outcome, released.relationship_id) == ("not_held", None)

    def _view_rows(self, *decisions):
        return [
            [
                decision.source_ref,
                decision.organization_id,
                decision.region,
                decision.assignee_user_id,
                decision.source_assignee_id,
                decision.allocated_at,
                decision.released_at,
                decision.source_releaser_id,
            ]
            for decision in decisions
        ]

    def test_reconciliation_applies_every_row_and_counts_outcomes(self):
        rows = self._view_rows(self._decision(), self._release(source_ref="never-delivered"))
        rows.append([TASK + "-bad", "org-1", "us", "not-a-user-id", "x", FENCE, None, None])
        rows.append([None, "org-1", "us", self.user.id, "x", FENCE, None, None])
        rows.append([TASK + "-fractional", "org-1", "us", self.user.id + 0.5, "x", FENCE, None, None])
        rows.append([TASK + "-decimal", "org-1", "us", Decimal(f"{self.user.id}.5"), "x", FENCE, None, None])

        with patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)) as read:
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert read.call_count == 1
        assert (result.decisions, result.outcomes) == (6, {"accepted": 1, "not_held": 1, "invalid": 4})
        holder = self._active_ae()
        assert holder is not None and holder.source_ref == TASK

    @parameterized.expand(["valid_sibling", "invalid_sibling"])
    def test_a_task_listed_more_than_once_is_not_applied(self, sibling):
        rows = self._view_rows(self._decision(), self._release())
        if sibling == "invalid_sibling":
            rows[1][DECISION_COLUMNS.index("allocated_at")] = "not-a-timestamp"

        with patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"duplicate": 1}
        assert self._active_ae() is None

    def test_a_timestamp_without_a_timezone_is_read_as_utc(self):
        rows = self._view_rows(self._decision())
        rows[0][5] = "2026-01-02T00:00:00"

        with patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"accepted": 1}

    @parameterized.expand([("distinct_tasks", [0, 1, 2], 0), ("a_task_split_across_pages", [0, 1, 1, 2], 1)])
    def test_the_view_is_read_to_the_end_in_pages(self, _name, task_indexes, duplicates):
        all_rows = self._view_rows(
            *(self._decision(source_ref=f"task-{index}", organization_id="org-none") for index in task_indexes)
        )

        def read_after_cursor(query, **_kwargs):
            after = [row for row in all_rows if str(row[0]) > query.where.right.value]
            return SimpleNamespace(results=after[: query.limit.value])

        with (
            patch.object(ownership_claims, "DECISION_PAGE_SIZE", 2),
            patch.object(ownership_claims, "execute_hogql_query", side_effect=read_after_cursor) as read,
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert read.call_count == 3
        assert result.decisions == len(task_indexes)
        assert result.outcomes.get("duplicate", 0) == duplicates

    def test_a_view_whose_task_id_does_not_page_as_text_is_reported(self):
        rows = self._view_rows(self._decision(source_ref="task-0"), self._decision(source_ref="task-1"))

        with (
            patch.object(ownership_claims, "DECISION_PAGE_SIZE", 2),
            patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)),
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"misconfigured": 1}

    def test_a_view_past_the_row_ceiling_is_refused_before_anything_is_applied(self):
        all_rows = self._view_rows(*(self._decision(source_ref=f"task-{index}") for index in range(4)))

        def read_after_cursor(query, **_kwargs):
            after = [row for row in all_rows if str(row[0]) > query.where.right.value]
            return SimpleNamespace(results=after[: query.limit.value])

        with (
            patch.object(ownership_claims, "DECISION_PAGE_SIZE", 2),
            patch.object(ownership_claims, "MAX_DECISION_ROWS", 1),
            patch.object(ownership_claims, "execute_hogql_query", side_effect=read_after_cursor),
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"misconfigured": 1}
        assert self._active_ae() is None

    def test_a_sweep_stops_between_decisions_when_asked(self):
        rows = self._view_rows(self._decision(source_ref="task-0"), self._decision(source_ref="task-1"))
        checks = iter([False, False, True])

        with (
            patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)),
            self.assertRaises(ownership_claims.SweepStopped),
        ):
            ownership_claims.reconcile_ownership_claims(self.team, should_stop=lambda: next(checks))

        claimed = AccountRelationship.objects.for_team(self.team.id).filter(source_ref__in=["task-0", "task-1"])
        assert claimed.count() == 1

    def _claim_raising_on_first_task(self, error):
        real_claim = ownership_claims.claim

        def claim(*, team, definition, decision):
            if decision.source_ref == "boom":
                raise error
            return real_claim(team=team, definition=definition, decision=decision)

        return claim

    def test_reconciliation_counts_a_collision_with_an_overlapping_sweep_and_continues(self):
        rows = self._view_rows(self._decision(source_ref="boom"), self._decision())
        claim = self._claim_raising_on_first_task(IntegrityError("unique_relationship_per_source_ref"))

        with (
            patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)),
            patch.object(ownership_claims, "claim", side_effect=claim),
            patch.object(ownership_claims, "capture_exception") as captured,
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"error": 1, "accepted": 1}
        captured.assert_called_once()
        assert self._active_ae() is not None

    def test_a_failing_dependency_ends_the_sweep_instead_of_counting_every_row(self):
        rows = self._view_rows(self._decision(source_ref="boom"), self._decision())
        claim = self._claim_raising_on_first_task(OperationalError("connection already closed"))

        with (
            patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)),
            patch.object(ownership_claims, "claim", side_effect=claim) as claimed,
            self.assertRaises(OperationalError),
        ):
            ownership_claims.reconcile_ownership_claims(self.team)

        assert claimed.call_count == 1
        assert self._active_ae() is None

    def test_rereading_an_accepted_task_under_another_organization_is_blocked(self):
        self._claim()
        other = create_account(team_id=self.team.id, name="Other", external_id="org-2")
        enroll_account(other, self.ae_definition, controlled_at=FENCE)

        moved = self._claim(organization_id="org-2")

        assert (moved.outcome, moved.reason) == ("blocked", "identity_mismatch")
        assert AccountRelationship.objects.for_team(self.team.id).filter(source_ref=TASK).count() == 1

    @parameterized.expand(["claims_disabled", "no_view_bound", "view_deleted"])
    def test_reconciliation_skips_a_project_that_is_not_set_up(self, case):
        if case == "claims_disabled":
            self.ae_definition.claims_enabled = False
            self.ae_definition.save(update_fields=["claims_enabled"])
        elif case == "no_view_bound":
            self.ae_definition.claim_saved_query = None
            self.ae_definition.save(update_fields=["claim_saved_query"])
        else:
            self.view.soft_delete()

        with patch.object(ownership_claims, "execute_hogql_query") as read:
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.skipped is True
        read.assert_not_called()

    @parameterized.expand(["missing_columns", "query_error"])
    def test_one_unusable_view_is_counted_and_the_others_still_run(self, fault):
        if fault == "missing_columns":
            self.view.columns = saved_query_columns(["task_id"])
            self.view.save(update_fields=["columns"])
        csm_definition, _ = self._claim_bound_definition("CSM", "csm_decisions")
        enroll_account(self.account, csm_definition, controlled_at=FENCE)
        rows = self._view_rows(self._decision(source_ref="task-csm"))

        def read_view(query, **_kwargs):
            if query.select_from.table.chain[0] == self.view.name:
                raise QueryError("Unknown table 'salesforce_task'")
            return SimpleNamespace(results=rows)

        with (
            patch.object(ownership_claims, "execute_hogql_query", side_effect=read_view) as read,
            patch.object(ownership_claims, "capture_exception") as captured,
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert (result.decisions, result.outcomes, result.skipped) == (1, {"misconfigured": 1, "accepted": 1}, False)
        assert read.call_count == (1 if fault == "missing_columns" else 2)
        captured.assert_called_once()
        holder = AccountRelationship.objects.for_team(self.team.id).get(account=self.account, ended_at__isnull=True)
        assert (holder.definition_id, holder.source_ref) == (csm_definition.id, "task-csm")

    def test_a_view_moved_mid_sweep_is_applied_under_its_new_definition_next_tick(self):
        csm_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM", is_controlled=True
        )
        enroll_account(self.account, csm_definition, controlled_at=FENCE)
        rows = self._view_rows(self._decision(source_ref="task-moved"))

        def move_view_then_answer(query, **_kwargs):
            ownership_claims.bind_claim_view(self.team.id, self.ae_definition.id, None)
            ownership_claims.bind_claim_view(self.team.id, csm_definition.id, self.view.id)
            ownership_claims.set_claims_enabled(self.team.id, csm_definition.id, True)
            return SimpleNamespace(results=rows)

        with patch.object(ownership_claims, "execute_hogql_query", side_effect=move_view_then_answer):
            during_move = ownership_claims.reconcile_ownership_claims(self.team)
        with patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)):
            next_tick = ownership_claims.reconcile_ownership_claims(self.team)

        assert during_move.outcomes == {"binding_changed": 1}
        assert next_tick.outcomes == {"accepted": 1}
        holder = AccountRelationship.objects.for_team(self.team.id).get(account=self.account, ended_at__isnull=True)
        assert (holder.definition_id, holder.source_ref) == (csm_definition.id, "task-moved")

    def test_a_bound_view_cannot_be_hard_deleted(self):
        with self.assertRaises(RestrictedError):
            self.view.delete()

    def test_only_projects_with_claims_on_and_a_view_bound_are_swept(self):
        claims_off = Team.objects.create(organization=self.organization, name="claims off")
        AccountRelationshipDefinition.objects.for_team(claims_off.id).create(
            team_id=claims_off.id,
            name="AE",
            is_controlled=True,
            claim_saved_query=create_saved_query(
                team_id=claims_off.id, name="decisions", columns=saved_query_columns(DECISION_COLUMNS)
            ),
        )
        no_view = Team.objects.create(organization=self.organization, name="no view")
        AccountRelationshipDefinition.objects.for_team(no_view.id).create(
            team_id=no_view.id, name="AE", is_controlled=True, claims_enabled=True
        )
        self._claim_bound_definition("CSM", "csm_decisions")

        assert ownership_claims.list_ownership_claim_team_ids() == [self.team.id]

    def test_each_claim_bound_definition_reads_its_own_view(self):
        csm_definition, csm_view = self._claim_bound_definition("CSM", "csm_decisions")
        enroll_account(self.account, csm_definition, controlled_at=FENCE)
        rows_by_view = {
            self.view.name: self._view_rows(self._decision(source_ref="task-ae")),
            csm_view.name: self._view_rows(self._decision(source_ref="task-csm")),
        }

        def read_view(query, **_kwargs):
            return SimpleNamespace(results=rows_by_view[query.select_from.table.chain[0]])

        with patch.object(ownership_claims, "execute_hogql_query", side_effect=read_view):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert (result.decisions, result.outcomes) == (2, {"accepted": 2})
        holders = AccountRelationship.objects.for_team(self.team.id).filter(account=self.account, ended_at__isnull=True)
        assert {holder.definition_id: holder.source_ref for holder in holders} == {
            self.ae_definition.id: "task-ae",
            csm_definition.id: "task-csm",
        }


@pytest.mark.asyncio
async def test_coordinator_starts_one_sweep_per_project_and_leaves_a_running_one_alone() -> None:
    team_ids = (11, 22, 33)
    start_child_workflow = AsyncMock(
        side_effect=[None, WorkflowAlreadyStartedError(ownership_claims_workflow_id(22), "sweep"), None]
    )
    with (
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.workflow.execute_activity",
            AsyncMock(return_value=OwnershipClaimsProjects(team_ids=team_ids)),
        ),
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.workflow.start_child_workflow",
            start_child_workflow,
        ),
    ):
        result = await OwnershipClaimsCoordinatorWorkflow().run(OwnershipClaimsCoordinatorInput())

    assert result == OwnershipClaimsCoordinatorOutput(enabled_teams=3, started_children=2, overlapping_children=1)
    assert [call.kwargs["id"] for call in start_child_workflow.await_args_list] == [
        ownership_claims_workflow_id(team_id) for team_id in team_ids
    ]
    for call in start_child_workflow.await_args_list:
        assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
        assert call.kwargs["parent_close_policy"] == ParentClosePolicy.ABANDON
        # Without a bound, a child that never runs holds its project's id and skips every later tick.
        assert call.kwargs["execution_timeout"] == OWNERSHIP_CLAIMS_SWEEP_EXECUTION_TIMEOUT


@pytest.mark.asyncio
async def test_a_coordinator_run_expires_before_the_next_tick() -> None:
    client = MagicMock()
    with (
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.a_schedule_exists",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.a_create_schedule", new=AsyncMock()
        ) as create_schedule,
    ):
        await create_ownership_claims_coordinator_schedule(client)

    assert create_schedule.await_args is not None
    schedule = create_schedule.await_args.args[2]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.action.execution_timeout == OWNERSHIP_CLAIMS_COORDINATOR_EXECUTION_TIMEOUT
    assert OWNERSHIP_CLAIMS_COORDINATOR_EXECUTION_TIMEOUT < OWNERSHIP_CLAIMS_INTERVAL


@pytest.mark.asyncio
async def test_schedule_update_keeps_an_operator_pause() -> None:
    paused = ScheduleState(paused=True, note="Repairing the bound view.")
    client = MagicMock()
    client.get_schedule_handle.return_value.describe = AsyncMock(
        return_value=SimpleNamespace(schedule=SimpleNamespace(state=paused))
    )
    with (
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.a_schedule_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "products.customer_analytics.backend.temporal.ownership_claims.a_update_schedule", new=AsyncMock()
        ) as update_schedule,
    ):
        await create_ownership_claims_coordinator_schedule(client)

    assert update_schedule.await_args is not None
    _, schedule_id, schedule = update_schedule.await_args.args
    assert schedule_id == OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID
    assert schedule.state == paused
