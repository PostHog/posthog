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

    def test_unbound_schedule_that_becomes_gated_by_drift_is_not_applied(self, _mock_enabled):
        # Stale-read bypass: scheduling an enable while the flag is already active binds no CR (the
        # change is a no-op at scheduling time, so the enable policy never fires). If the flag is
        # disabled before the fire window, dispatching ungated would re-enable it with the enable
        # policy never consulted. The fire-time re-gate must catch the drift and skip the change.
        self._enable_policy()
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="already-active-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=True,
            created_by=self.user,
        )

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        # No-op against the then-active flag: nothing bound.
        assert scheduled.change_request is None

        # Flag drifts to disabled, then the fire window opens.
        flag.active = False
        flag.save()
        scheduled.scheduled_at = timezone.now() - timedelta(seconds=30)
        scheduled.save()

        process_scheduled_changes()

        flag.refresh_from_db()
        # The enable must not have applied — a policy now gates it and it was never approved.
        assert flag.active is False

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
        self._org_enable_policy()  # org-level policy also matches the enable, creating the conflict
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

    def test_patching_gated_schedule_with_same_action_reuses_bound_cr(self, _mock_enabled):
        # Re-gating a gated schedule whose payload edit keeps the same gated action must reuse the
        # row's own pending CR — not fail closed on it as a duplicate, and not mint a second one.
        # This is the only path that reaches the current_change_request reuse branch in
        # gate_scheduled_change (every other PATCH test goes ungated↔gated).
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        original_cr = scheduled.change_request
        assert original_cr is not None and original_cr.state == ChangeRequestState.PENDING

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/",
            {"payload": {"operation": "update_status", "value": True}},
            format="json",
        )

        assert response.status_code == 200, response.content
        reloaded = ScheduledChange.objects.get(id=scheduled.id)
        assert reloaded.change_request is not None
        assert reloaded.change_request.id == original_cr.id
        assert reloaded.change_request.state == ChangeRequestState.PENDING
        # No second CR minted for the flag — the schedule's own binding was reused.
        assert ChangeRequest.objects.filter(resource_id=str(flag.id)).count() == 1

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

    def test_second_schedule_cannot_bind_an_unapproved_pending_change_request(self, _mock_enabled):
        # A second schedule for the same flag+action must not ride the first schedule's still-pending
        # CR: once that CR is approved, the earlier-timed second schedule would fire it before the
        # window the approval was created for. Binding across schedules must fail closed.
        self._enable_policy()
        flag = self._disabled_flag()

        first = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=2),
        )
        cr = first.change_request
        assert cr is not None and cr.state == ChangeRequestState.PENDING

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            {
                "record_id": str(flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": (timezone.now() + timedelta(minutes=5)).isoformat(),
            },
            format="json",
        )

        assert response.status_code == 409, response.content
        assert response.json()["code"] == "change_request_pending"
        # The second schedule is not created, and no new CR bound to the first's pending request.
        assert ScheduledChange.objects.filter(record_id=str(flag.id)).count() == 1
        assert ChangeRequest.objects.filter(resource_id=str(flag.id)).count() == 1

    def _recurring_enable_schedule(self, flag: FeatureFlag, *, gated: bool) -> ScheduledChange:
        payload = {"operation": "update_status", "value": True}
        return ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=timezone.now() - timedelta(seconds=30),
            is_recurring=True,
            recurrence_interval="daily",
            created_by=self.user,
            change_request=self._gate(flag, payload) if gated else None,
        )

    def _org_enable_policy(self) -> ApprovalPolicy:
        # Org-level (team=None) enable policy — matches the same enable as the team-level one, so a
        # change gated by both fails closed with a policy conflict.
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=None,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def test_regate_recurring_binds_fresh_cr_when_policy_applies(self, _mock_enabled):
        # regate_recurring_scheduled_change re-evaluates the flag's current state for the next
        # occurrence. With a matching policy enabled it binds a fresh pending CR — this is what lets
        # process_scheduled_changes re-gate a schedule (including one born ungated, change_request
        # None) instead of flipping the gated field unapproved on every recurrence.
        from products.approvals.backend.scheduled_changes import regate_recurring_scheduled_change

        self._enable_policy()
        flag = self._disabled_flag()
        scheduled = self._recurring_enable_schedule(flag, gated=False)
        assert scheduled.change_request is None

        cr = regate_recurring_scheduled_change(scheduled, flag)

        assert cr is not None
        assert cr.state == ChangeRequestState.PENDING

    def test_regate_recurring_raises_on_policy_conflict(self, _mock_enabled):
        # When the next occurrence would match more than one enabled policy, regate fails closed with
        # PolicyConflict rather than binding a single CR that can't satisfy both.
        from products.approvals.backend.exceptions import PolicyConflict
        from products.approvals.backend.scheduled_changes import regate_recurring_scheduled_change

        self._enable_policy()
        self._org_enable_policy()
        flag = self._disabled_flag()
        scheduled = self._recurring_enable_schedule(flag, gated=False)

        with self.assertRaises(PolicyConflict):
            regate_recurring_scheduled_change(scheduled, flag)

    def test_recurring_regate_conflict_does_not_advance_schedule(self, _mock_enabled):
        # process_scheduled_changes re-gates before advancing scheduled_at. If the next occurrence's
        # re-gate raises PolicyConflict, that must propagate before the advance is persisted, so the
        # schedule stays on the conflicting occurrence (failure recorded) rather than silently
        # skipping ahead. The bound CR keeps the flag disabled: the pending CR is expired at fire
        # time without applying, so re-gating sees the unchanged (disabled) flag and conflicts.
        self._enable_policy()
        flag = self._disabled_flag()
        scheduled = self._recurring_enable_schedule(flag, gated=True)
        assert scheduled.change_request is not None

        # A second enable policy makes the next occurrence's re-gate match two policies → conflict.
        self._org_enable_policy()

        process_scheduled_changes()

        scheduled.refresh_from_db()
        # scheduled_at not advanced into the future (a daily advance would push it ~1 day out) — the
        # conflicting occurrence is not skipped.
        assert scheduled.scheduled_at < timezone.now()
        assert scheduled.executed_at is None
        assert scheduled.failure_count == 1
        flag.refresh_from_db()
        assert flag.active is False

    def test_deleting_scheduled_change_expires_bound_pending_cr(self, _mock_enabled):
        # Deleting a gated schedule must expire its bound pending CR. Otherwise the CR outlives the
        # schedule and, on reaching quorum, ChangeRequestService.approve() auto-applies it
        # immediately — its scheduled-deferral keys off the now-deleted schedule row, so the flag
        # change fires without the schedule it was approved for.
        self._enable_policy()
        flag = self._disabled_flag()

        scheduled = self._schedule(
            flag,
            {"operation": "update_status", "value": True},
            timezone.now() + timedelta(hours=1),
        )
        cr = scheduled.change_request
        assert cr is not None and cr.state == ChangeRequestState.PENDING

        response = self.client.delete(f"/api/projects/{self.team.id}/scheduled_changes/{scheduled.id}/")

        assert response.status_code == 204, response.content
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.EXPIRED
        flag.refresh_from_db()
        assert flag.active is False

    def test_failed_row_insert_rolls_back_the_created_cr(self, _mock_enabled):
        # create() mints the pending CR and inserts the bound row in one transaction. If the row
        # insert fails after the CR is created, the CR must roll back with it — otherwise it is
        # orphaned, and once it reaches quorum ChangeRequestService.approve() auto-applies it
        # immediately (its scheduled-deferral keys off a schedule row that never got saved),
        # bypassing the schedule. Guards the create() transaction boundary.
        from django.db import IntegrityError

        from rest_framework import serializers

        self._enable_policy()
        flag = self._disabled_flag()

        # Fail the row insert (super().create) after the gate has minted the pending CR.
        with patch.object(serializers.ModelSerializer, "create", side_effect=IntegrityError("boom")):
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

        assert response.status_code == 500, response.content
        # The atomic wrap rolled the minted CR back with the failed row insert; neither survives.
        assert ChangeRequest.objects.count() == 0
        assert ScheduledChange.objects.filter(record_id=str(flag.id)).count() == 0

    def test_rolled_back_orphan_cr_does_not_notify_approvers(self, _mock_enabled):
        # The approver notification is deferred to transaction.on_commit, so a rolled-back orphan CR
        # (the row insert fails after the gate mints the CR) must NOT ping an approver about a change
        # request that no longer exists. Django's TestCase wraps each test in a transaction, so an
        # on_commit callback only runs if the outer block explicitly commits; here the inner atomic
        # rolls back, so the callback is discarded and the notification never fires.
        from django.db import IntegrityError

        from rest_framework import serializers

        self._enable_policy()
        flag = self._disabled_flag()

        with patch("products.approvals.backend.decorators.send_approval_requested_notification") as mock_notify:
            with patch.object(serializers.ModelSerializer, "create", side_effect=IntegrityError("boom")):
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

        assert response.status_code == 500, response.content
        assert ChangeRequest.objects.count() == 0
        mock_notify.assert_not_called()

    def test_successful_scheduled_create_notifies_approvers_once(self, _mock_enabled):
        # Happy path for the deferred notification: on a successful gated scheduled create the CR
        # commits and the on_commit callback fires exactly once. captureOnCommitCallbacks(execute=True)
        # is required because TestCase's surrounding transaction otherwise swallows on_commit.
        self._enable_policy()
        flag = self._disabled_flag()

        with patch("products.approvals.backend.decorators.send_approval_requested_notification") as mock_notify:
            with self.captureOnCommitCallbacks(execute=True):
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

        assert response.status_code == 201, response.content
        cr = ChangeRequest.objects.get(resource_id=str(flag.id))
        assert cr.state == ChangeRequestState.PENDING
        mock_notify.assert_called_once_with(cr)

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

    def test_recurring_approved_then_stale_cr_survives_and_regates(self, _mock_enabled):
        # A recurring schedule whose bound CR is approved-but-stale must not die at fire time. The
        # stale CR is expired (not applied), then the next occurrence re-gates to a fresh pending CR
        # and the schedule advances — rather than leaving the stale-approved CR in [PENDING, APPROVED]
        # for the flag-scoped duplicate check to rediscover, raise ApprovalRequired on, and retry to
        # exhaustion. This exercises the regate path that the one-time variant above never reaches.
        self._enable_policy()
        flag = self._disabled_flag()
        scheduled = self._recurring_enable_schedule(flag, gated=True)
        old_cr = scheduled.change_request
        assert old_cr is not None

        old_cr.state = ChangeRequestState.APPROVED
        old_cr.validation_status = ValidationStatus.STALE
        old_cr.save()

        process_scheduled_changes()

        old_cr.refresh_from_db()
        assert old_cr.state == ChangeRequestState.EXPIRED
        scheduled.refresh_from_db()
        # Survived: advanced to a future occurrence, still active, no failures recorded.
        assert scheduled.scheduled_at > timezone.now()
        assert scheduled.executed_at is None
        assert scheduled.failure_count == 0
        # Rebound to a fresh pending CR for the next occurrence, not the expired one.
        assert scheduled.change_request is not None
        assert scheduled.change_request.id != old_cr.id
        assert scheduled.change_request.state == ChangeRequestState.PENDING
        # The stale change never applied.
        flag.refresh_from_db()
        assert flag.active is False
