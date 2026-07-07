from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import User
from posthog.tasks.process_scheduled_changes import process_scheduled_changes

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState, ValidationStatus
from products.approvals.backend.services import ChangeRequestService
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestScheduledChangeGating(APIBaseTest):
    """A scheduled change that would flip a policy-gated field must not apply without approval.

    Gating happens at scheduling time (a pending ChangeRequest is bound to the row); the Celery
    applier only applies once that CR is approved, and expires it if the fire window closes first.
    """

    def _disabled_flag(self, key: str = "sched-flag") -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=False,
            created_by=self.user,
        )

    def _enable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _update_policy(self, conditions: dict[str, Any] | None = None) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions=conditions if conditions is not None else {},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _schedule(self, flag: FeatureFlag, payload: dict, scheduled_at: datetime) -> ScheduledChange:
        return ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=scheduled_at,
            created_by=self.user,
            change_request=self._gate(flag, payload),
        )

    def _gate(self, flag: FeatureFlag, payload: dict) -> ChangeRequest | None:
        from products.approvals.backend.scheduled_changes import gate_scheduled_change

        return gate_scheduled_change(flag, payload, self.user)

    def test_scheduled_enable_under_policy_creates_pending_cr_and_does_not_apply(self, _mock_enabled):
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            datetime.now(UTC) - timedelta(seconds=30),
        )

        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPROVED).count() == 0

        process_scheduled_changes()

        flag.refresh_from_db()
        assert flag.active is False
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED

    def test_approving_scheduled_cr_defers_apply_to_fire_time(self, _mock_enabled):
        # A scheduled change's CR must not apply on approval: reaching quorum before scheduled_at
        # would let an approver fire a future-dated flag change early. The CR stays APPROVED and
        # only the scheduled applier flips the flag once the fire window is reached.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        cr = scheduled.change_request
        assert cr is not None

        ChangeRequestService(cr, self.user).approve()

        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPROVED
        flag.refresh_from_db()
        assert flag.active is False

        # Move the fire window into the past and let the applier apply via the approved path.
        scheduled.scheduled_at = timezone.now() - timedelta(seconds=30)
        scheduled.save()
        process_scheduled_changes()

        # Reload into a fresh instance so the narrowed type from the earlier assert is widened.
        flag = FeatureFlag.objects.get(pk=flag.pk)
        assert flag.active is True
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPLIED

    def test_pending_cr_past_window_is_expired_and_change_skipped(self, _mock_enabled):
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() - timedelta(seconds=30),
        )
        cr = scheduled.change_request
        assert cr is not None
        assert cr.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.EXPIRED
        flag.refresh_from_db()
        assert flag.active is False
        scheduled.refresh_from_db()
        assert scheduled.executed_at is not None

    def test_scheduled_rollout_change_under_update_policy_is_gated(self, _mock_enabled):
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})
        flag = self._disabled_flag(key="rollout-flag")

        new_condition: dict[str, Any] = {
            "variant": None,
            "properties": [],
            "rollout_percentage": 90,
            "aggregation_group_type_index": None,
        }
        scheduled = self._schedule(
            flag,
            {
                "operation": "add_release_condition",
                "value": {"groups": [new_condition], "payloads": {}, "multivariate": None},
            },
            timezone.now() - timedelta(seconds=30),
        )

        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        flag.refresh_from_db()
        # The new 90% condition must not have been appended (change was gated, not applied).
        rollouts = [g.get("rollout_percentage") for g in flag.filters.get("groups", [])]
        assert 90 not in rollouts
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED

    def test_scheduled_change_matching_multiple_policies_is_rejected(self, _mock_enabled):
        # A scheduled enable that matches more than one enabled policy can't be bound to a single
        # CR. It must fail closed at creation (400) with no row, rather than save ungated and let
        # the Celery applier dispatch it with no approval at all.
        self._enable_policy()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=None,  # org-level policy also matches the enable, creating the conflict
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        flag = self._disabled_flag()

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            {
                "record_id": str(flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )

        assert response.status_code == 400, response.content
        assert response.json()["code"] == "policy_conflict"
        assert ScheduledChange.objects.filter(record_id=str(flag.id)).count() == 0

    def test_scheduled_change_without_policy_applies_normally(self, _mock_enabled):
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            datetime.now(UTC) - timedelta(seconds=30),
        )
        assert scheduled.change_request is None

        process_scheduled_changes()

        flag.refresh_from_db()
        assert flag.active is True
        scheduled.refresh_from_db()
        assert scheduled.executed_at is not None

    def test_patching_payload_to_gated_change_binds_pending_cr(self, _mock_enabled):
        # create() only gates the initial payload. A schedule born harmless (a disable, ungated
        # because no disable policy) must not become a way to apply a gated enable when its payload
        # is later PATCHed — the update path re-runs the gate and binds a pending CR.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": False},
            timezone.now() + timedelta(hours=1),
        )
        assert scheduled.change_request is None

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/",
            {"payload": {"operation": "update_status", "value": True}},
            format="json",
        )

        assert response.status_code == 200, response.content
        reloaded = ScheduledChange.objects.get(id=scheduled.id)
        assert reloaded.change_request is not None
        assert reloaded.change_request.state == ChangeRequestState.PENDING

    def test_patching_payload_to_ungated_change_expires_stale_cr(self, _mock_enabled):
        # The inverse: a gated schedule repointed at an ungated payload must drop its binding and
        # expire the now-orphaned pending CR, so it can't be approved into applying the old change.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        old_cr = scheduled.change_request
        assert old_cr is not None and old_cr.state == ChangeRequestState.PENDING

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/",
            {"payload": {"operation": "update_status", "value": False}},
            format="json",
        )

        assert response.status_code == 200, response.content
        scheduled.refresh_from_db()
        assert scheduled.change_request is None
        old_cr.refresh_from_db()
        assert old_cr.state == ChangeRequestState.EXPIRED

    def test_regate_on_payload_change_gates_as_editing_user_not_creator(self, _mock_enabled):
        # Re-gating must evaluate as the user making the edit, not the schedule's creator: a creator
        # with approval bypass would otherwise let any editor PATCH in a gated payload that stays
        # unbound and applies unapproved. The bound CR is attributed to the editor.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": False},
            timezone.now() + timedelta(hours=1),
        )
        assert scheduled.change_request is None

        editor = User.objects.create_and_join(self.organization, "editor@posthog.com", None)
        self.client.force_login(editor)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/",
            {"payload": {"operation": "update_status", "value": True}},
            format="json",
        )

        assert response.status_code == 200, response.content
        reloaded = ScheduledChange.objects.get(id=scheduled.id)
        assert reloaded.change_request is not None
        assert reloaded.change_request.created_by == editor
        assert reloaded.change_request.created_by != self.user

    def test_scheduled_variant_rollout_change_under_policy_is_gated(self, _mock_enabled):
        # update_variants writes into the flag's live multivariate filters. Unless the gate deep-copies
        # first, the in-place mutation makes detect() compare the changed rollout against itself, bind
        # no CR, and let the variant change dispatch unapproved.
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="variant-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
            active=True,
            created_by=self.user,
        )

        scheduled = self._schedule(
            flag,
            {
                "operation": "update_variants",
                "value": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 20},
                        {"key": "test", "rollout_percentage": 80},
                    ]
                },
            },
            timezone.now() - timedelta(seconds=30),
        )

        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        flag.refresh_from_db()
        variant_rollouts = {v["key"]: v["rollout_percentage"] for v in flag.filters["multivariate"]["variants"]}
        # The gated change must not have applied — variants stay at their original 50/50 split.
        assert variant_rollouts == {"control": 50, "test": 50}
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED

    def test_cannot_retime_a_gated_schedule_with_live_change_request(self, _mock_enabled):
        # An approver signs off on a change firing in a specific window. Retiming an approved schedule
        # to fire immediately applies it outside the approval, so timing edits are blocked while the
        # bound CR is pending or approved.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=2),
        )
        cr = scheduled.change_request
        assert cr is not None
        ChangeRequestService(cr, self.user).approve()
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPROVED

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/",
            {"scheduled_at": (timezone.now() - timedelta(seconds=30)).isoformat()},
            format="json",
        )

        assert response.status_code == 400, response.content
        scheduled.refresh_from_db()
        assert scheduled.scheduled_at > timezone.now()

    def test_second_schedule_cannot_bind_an_already_approved_change_request(self, _mock_enabled):
        # A second schedule for the same flag+action would bind the first schedule's already-approved
        # CR via duplicate detection and could fire it at an arbitrary time. It must fail closed.
        self._enable_policy()
        flag = self._disabled_flag()

        first = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=2),
        )
        cr = first.change_request
        assert cr is not None
        ChangeRequestService(cr, self.user).approve()
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPROVED

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            {
                "record_id": str(flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": (timezone.now() - timedelta(seconds=30)).isoformat(),
            },
            format="json",
        )

        assert response.status_code == 409, response.content
        assert response.json()["code"] == "change_request_pending"
        assert ScheduledChange.objects.filter(record_id=str(flag.id)).count() == 1
        flag.refresh_from_db()
        assert flag.active is False

    def _recurring_rollout_schedule(self, flag: FeatureFlag, scheduled_at: datetime) -> ScheduledChange:
        # add_release_condition appends a >0 rollout group on every fire, so each occurrence is a real
        # change the rollout policy can gate (unlike re-asserting an already-set active flag).
        new_condition: dict[str, Any] = {
            "variant": None,
            "properties": [],
            "rollout_percentage": 90,
            "aggregation_group_type_index": None,
        }
        return ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload={
                "operation": "add_release_condition",
                "value": {"groups": [new_condition], "payloads": {}, "multivariate": None},
            },
            scheduled_at=scheduled_at,
            is_recurring=True,
            recurrence_interval="daily",
            created_by=self.user,
            change_request=None,
        )

    def test_recurring_schedule_born_ungated_regates_when_policy_added_later(self, _mock_enabled):
        # A recurring schedule created before any policy existed binds no CR. Once a matching policy
        # is enabled, every future occurrence must be re-gated — the applier re-gates on each advance
        # regardless of the current (null) binding, so the next fire is gated rather than flipping the
        # rollout unapproved forever.
        flag = self._disabled_flag(key="recurring-late-policy")
        scheduled = self._recurring_rollout_schedule(flag, timezone.now() - timedelta(seconds=30))
        assert scheduled.change_request is None

        # Policy enabled *after* the schedule was created.
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})

        process_scheduled_changes()

        # Reload into a fresh instance so the narrowed type from the earlier `is None` assert is widened.
        reloaded = ScheduledChange.objects.get(pk=scheduled.pk)
        # The next occurrence is now gated: re-gating bound a fresh pending CR during the advance.
        assert reloaded.change_request is not None
        assert reloaded.change_request.state == ChangeRequestState.PENDING
        # Still an active recurring schedule pointed at a future fire (not completed).
        assert reloaded.executed_at is None
        assert reloaded.scheduled_at > timezone.now()

    def test_recurring_regate_conflict_stops_advancing_schedule(self, _mock_enabled):
        # If the next occurrence would match more than one enabled policy, re-gating raises
        # PolicyConflict. That must propagate before scheduled_at is advanced, so the schedule stays
        # on the conflicting occurrence (failure recorded) instead of silently skipping to the next.
        flag = self._disabled_flag(key="recurring-conflict")
        scheduled = self._recurring_rollout_schedule(flag, timezone.now() - timedelta(seconds=30))

        # Two enabled update policies both match the rollout change → conflict at re-gate time.
        rollout_condition = {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0}
        self._update_policy(rollout_condition)
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=None,  # org-level, also matches the rollout change
            action_key="feature_flag.update",
            conditions=rollout_condition,
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        process_scheduled_changes()

        scheduled.refresh_from_db()
        # scheduled_at was not advanced into the future — the conflicting occurrence is not skipped.
        assert scheduled.scheduled_at < timezone.now()
        assert scheduled.executed_at is None
        assert scheduled.failure_count == 1
        assert scheduled.failure_reason is not None

    def test_approved_then_stale_cr_is_not_applied(self, _mock_enabled):
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        cr = scheduled.change_request
        assert cr is not None

        # Force the approved-but-stale combination: applier must skip (not apply) a stale CR.
        cr.state = ChangeRequestState.APPROVED
        cr.validation_status = ValidationStatus.STALE
        cr.save()

        scheduled.scheduled_at = timezone.now() - timedelta(seconds=30)
        scheduled.save()
        process_scheduled_changes()

        flag.refresh_from_db()
        assert flag.active is False
