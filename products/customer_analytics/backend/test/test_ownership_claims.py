from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import ScheduleState
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic import ownership_claims, relationships
from products.customer_analytics.backend.logic.ownership_claims import DECISION_COLUMNS
from products.customer_analytics.backend.models import (
    AccountRelationship,
    AccountRelationshipDefinition,
    TeamCustomerAnalyticsConfig,
)
from products.customer_analytics.backend.temporal.ownership_claims import (
    OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID,
    OwnershipClaimsCoordinatorInput,
    OwnershipClaimsCoordinatorOutput,
    OwnershipClaimsCoordinatorWorkflow,
    OwnershipClaimsProjects,
    create_ownership_claims_coordinator_schedule,
    ownership_claims_workflow_id,
)
from products.customer_analytics.backend.test.factories import create_account, create_saved_query

FENCE = datetime(2026, 1, 1, tzinfo=UTC)
TASK = "example-salesforce-task-17"


class TestOwnershipClaims(BaseTest):
    def setUp(self):
        super().setUp()
        self.ae_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Account executive"
        )
        self.view = create_saved_query(
            team_id=self.team.id, name="ownership_decisions", columns=dict.fromkeys(DECISION_COLUMNS, {})
        )
        self.config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        self.config.ae_relationship_definition = self.ae_definition
        self.config.ownership_claims_enabled = True
        self.config.ownership_claim_saved_query = self.view
        self.config.save(
            update_fields=["ae_relationship_definition", "ownership_claims_enabled", "ownership_claim_saved_query"]
        )
        self.account = create_account(
            team_id=self.team.id, name="Acme Corp", external_id="org-1", ae_ownership_controlled_at=FENCE
        )
        self.human = relationships.Actor.human(self.user)

    def _decision(self, **overrides) -> contracts.OwnershipClaimDecision:
        fields = {
            "source_ref": TASK,
            "organization_id": "org-1",
            "region": "us",
            "assignee_user_id": self.user.id,
            "source_assignee_id": "example-salesforce-user-17",
            "allocated_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
        fields.update(overrides)
        return contracts.OwnershipClaimDecision(**fields)

    def _release(self, **overrides) -> contracts.OwnershipClaimDecision:
        return self._decision(
            released_at=datetime(2026, 1, 3, tzinfo=UTC), source_releaser_id="example-salesforce-user-99", **overrides
        )

    def _claim(self, **overrides) -> contracts.OwnershipClaimResult:
        return relationships.claim_initial_ae(team=self.team, decision=self._decision(**overrides))

    def _release_claim(self, **overrides) -> contracts.OwnershipClaimResult:
        return relationships.release_initial_ae(team=self.team, decision=self._release(**overrides))

    def _active_ae(self) -> AccountRelationship | None:
        return (
            AccountRelationship.objects.for_team(self.team.id)
            .filter(account=self.account, definition=self.ae_definition, ended_at__isnull=True)
            .first()
        )

    def _fence(self) -> datetime | None:
        self.account.refresh_from_db()
        return self.account.ae_ownership_controlled_at

    def _assign_by_human(self, user: User) -> AccountRelationship:
        return relationships.assign(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, user=user, actor=self.human
        )

    def test_claim_fills_an_empty_managed_role(self):
        result = self._claim()

        assert result.outcome == "accepted"
        holder = self._active_ae()
        assert holder is not None and result.relationship_id == holder.id
        assert (holder.user_id, holder.source, holder.source_ref) == (self.user.id, "salesforce_claim", TASK)
        fence = self._fence()
        assert fence is not None and fence > FENCE and result.controlled_at == fence
        activity = ActivityLog.objects.get(team_id=self.team.id, scope="Account", activity="role_claimed")
        assert activity.is_system
        assert activity.detail["context"]["source_ref"] == TASK
        assert activity.detail["context"]["source_actor_id"] == "example-salesforce-user-17"

    def test_rereading_an_accepted_task_answers_the_original_decision_after_a_human_clear(self):
        first = self._claim()
        relationships.end_active(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
        )
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
            ("role_unbound", "blocked", "role_unbound"),
            ("unknown_organization", "blocked", "account_not_found"),
            ("region_mismatch", "blocked", "identity_mismatch"),
            ("assignee_not_a_member", "blocked", "assignee_not_member"),
            ("different_case_is_the_same_identity", "accepted", None),
        ]
    )
    def test_claim_decision_outcome(self, case, outcome, reason):
        overrides = {}
        if case == "occupied_by_another_user":
            self._assign_by_human(self._create_user("other@posthog.com"))
        elif case == "occupied_by_the_same_user":
            self._assign_by_human(self.user)
        elif case == "allocated_within_the_skew_allowance":
            overrides["allocated_at"] = datetime(2026, 1, 1, 0, 4, 59, tzinfo=UTC)
        elif case == "allocated_before_a_human_clear":
            relationships.end_active(
                team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
            )
        elif case == "allocated_in_the_future":
            overrides["allocated_at"] = timezone.now() + timedelta(days=1)
        elif case == "role_not_managed":
            self.account.ae_ownership_controlled_at = None
            self.account.save(update_fields=["ae_ownership_controlled_at"])
        elif case == "role_unbound":
            self.config.ae_relationship_definition = None
            self.config.save(update_fields=["ae_relationship_definition"])
        elif case == "unknown_organization":
            overrides["organization_id"] = "org-2"
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
        assert fence is not None and fence_after_claim is not None and fence > fence_after_claim
        activity = ActivityLog.objects.get(team_id=self.team.id, activity="role_released")
        assert activity.detail["context"]["source_actor_id"] == "example-salesforce-user-99"
        assert activity.detail["context"]["source_decided_at"] == "2026-01-03T00:00:00+00:00"

        repeated = self._release_claim()

        assert repeated.outcome == "not_held"
        assert self._fence() == fence
        assert ActivityLog.objects.filter(team_id=self.team.id, activity="role_released").count() == 1

    @parameterized.expand(["after_a_human_transfer", "after_a_human_clear"])
    def test_release_after_a_human_decision_is_not_held(self, decision):
        self._claim()
        if decision == "after_a_human_transfer":
            self._assign_by_human(self._create_user("successor@posthog.com"))
        else:
            relationships.end_active(
                team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
            )
        holder_before = self._active_ae()
        fence_before = self._fence()

        released = self._release_claim()

        assert released.outcome == "not_held"
        assert self._active_ae() == holder_before
        assert self._fence() == fence_before

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

        with patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)) as read:
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert read.call_count == 1
        assert (result.decisions, result.outcomes) == (5, {"accepted": 1, "not_held": 1, "invalid": 3})
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

    def test_reconciliation_counts_a_raising_decision_and_continues(self):
        rows = self._view_rows(self._decision(source_ref="boom"), self._decision())
        real_claim = relationships.claim_initial_ae

        def claim(*, team, decision):
            if decision.source_ref == "boom":
                raise RuntimeError("index collision")
            return real_claim(team=team, decision=decision)

        with (
            patch.object(ownership_claims, "execute_hogql_query", return_value=SimpleNamespace(results=rows)),
            patch.object(ownership_claims.relationships, "claim_initial_ae", side_effect=claim),
            patch.object(ownership_claims, "capture_exception") as captured,
        ):
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.outcomes == {"error": 1, "accepted": 1}
        captured.assert_called_once()
        assert self._active_ae() is not None

    def test_rereading_an_accepted_task_under_another_organization_is_blocked(self):
        self._claim()
        create_account(team_id=self.team.id, name="Other", external_id="org-2", ae_ownership_controlled_at=FENCE)

        moved = self._claim(organization_id="org-2")

        assert (moved.outcome, moved.reason) == ("blocked", "identity_mismatch")
        assert AccountRelationship.objects.for_team(self.team.id).filter(source_ref=TASK).count() == 1

    @parameterized.expand(["claims_disabled", "no_view_bound", "view_deleted"])
    def test_reconciliation_skips_a_project_that_is_not_set_up(self, case):
        if case == "claims_disabled":
            self.config.ownership_claims_enabled = False
            self.config.save(update_fields=["ownership_claims_enabled"])
        elif case == "no_view_bound":
            self.config.ownership_claim_saved_query = None
            self.config.save(update_fields=["ownership_claim_saved_query"])
        else:
            self.view.soft_delete()

        with patch.object(ownership_claims, "execute_hogql_query") as read:
            result = ownership_claims.reconcile_ownership_claims(self.team)

        assert result.skipped is True
        read.assert_not_called()

    def test_reconciliation_refuses_a_view_missing_decision_columns(self):
        self.view.columns = {"task_id": {}}
        self.view.save(update_fields=["columns"])

        with self.assertRaises(ownership_claims.ClaimSourceMisconfigured):
            ownership_claims.reconcile_ownership_claims(self.team)

    def test_only_projects_with_claims_on_and_a_view_bound_are_swept(self):
        claims_off = Team.objects.create(organization=self.organization, name="claims off")
        claims_off_config = get_or_create_team_extension(claims_off, TeamCustomerAnalyticsConfig)
        claims_off_config.ownership_claim_saved_query = create_saved_query(
            team_id=claims_off.id, name="decisions", columns=dict.fromkeys(DECISION_COLUMNS, {})
        )
        claims_off_config.save(update_fields=["ownership_claim_saved_query"])
        no_view = Team.objects.create(organization=self.organization, name="no view")
        no_view_config = get_or_create_team_extension(no_view, TeamCustomerAnalyticsConfig)
        no_view_config.ownership_claims_enabled = True
        no_view_config.save(update_fields=["ownership_claims_enabled"])

        assert ownership_claims.list_ownership_claim_team_ids() == [self.team.id]


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

    _, schedule_id, schedule = update_schedule.await_args.args
    assert schedule_id == OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID
    assert schedule.state == paused
