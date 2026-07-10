"""Consolidated adversarial bypass matrix for feature-flag approval gating.

This is the living catalog of every mutation path that can change a policy-gated
feature-flag field, and the regression lock proving each one routes through the
approval gate. The headline invariant: with an enabled policy, NOTHING changes a
gated field without an approval — every write either creates a pending ChangeRequest
and leaves the flag untouched, or (for the control cases) applies normally because no
policy guards it.

Each closed bypass below maps to a fix on this branch:
  - direct PATCH enable/disable/update        -> the baseline control the gate exists for
  - experiment launch / pause / resume        -> flag flips routed through FeatureFlagSerializer
  - experiment ship_variant                   -> variant rollout rewrite gated by feature_flag.update
  - web-experiment variant rollout edit        -> update_experiment() variant write, gated by feature_flag.update
  - copy onto existing-active / copy-as-active -> copy_flags lands the row in a guarded state
  - create-active / create-rollout             -> create() born in a guarded state
  - delete + recreate-as-active                -> re-create path is gated like any other create
  - scheduled update_status / rollout change   -> gated at scheduling time, expired if the window closes first

The per-path detection/extract/end-to-end edge cases live in the dedicated task test
files (test_decorators, test_update_feature_flag_action, test_create_feature_flag_gate,
test_scheduled_change_gating, test_experiment_service_approvals, and the copy gate class
in products/feature_flags/.../test_organization_feature_flag.py). This file asserts the
headline "gated field UNCHANGED + a pending ChangeRequest created + 0 applied" outcome for
each path in one place so a future regression on any single bypass fails loudly here.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature
from posthog.tasks.process_scheduled_changes import process_scheduled_changes

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import ChangeRequestService
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange


def _enable_policy_for(test: "FeatureFlagBypassMatrixBase", action_key: str) -> ApprovalPolicy:
    return ApprovalPolicy.objects.create(
        organization=test.organization,
        team=test.team,
        action_key=action_key,
        conditions={},
        approver_config={"quorum": 1, "users": [test.user.id]},
        created_by=test.user,
    )


def _any_rollout_change_policy(test: "FeatureFlagBypassMatrixBase") -> ApprovalPolicy:
    # >0 from an empty/zero baseline fires on any non-trivial rollout write.
    return ApprovalPolicy.objects.create(
        organization=test.organization,
        team=test.team,
        action_key="feature_flag.update",
        conditions={"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0},
        approver_config={"quorum": 1, "users": [test.user.id]},
        created_by=test.user,
    )


class FeatureFlagBypassMatrixBase(APIBaseTest):
    """Shared setup. Concrete subclasses force the approvals feature on via the
    _is_approvals_enabled patch, matching the convention used across the per-task tests."""

    def _flag(self, *, active: bool, key: str = "matrix-flag", rollout: int = 50) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            filters={"groups": [{"properties": [], "rollout_percentage": rollout}]},
            active=active,
            created_by=self.user,
        )

    def _assert_one_pending_zero_applied(self) -> None:
        assert ChangeRequest.objects.filter(state=ChangeRequestState.PENDING).count() == 1
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPLIED).count() == 0


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestDirectAndCreateBypassMatrix(FeatureFlagBypassMatrixBase):
    """Paths that run through FeatureFlagSerializer.update()/create() over the public flag API.

    Each case: drive the mutation under an enabled policy, then assert the gated field is
    UNCHANGED, exactly one pending ChangeRequest exists, and nothing was applied.
    """

    def _patch(self, flag: FeatureFlag, data: dict[str, Any]) -> Any:
        return self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", data, format="json")

    def _post(self, data: dict[str, Any]) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/feature_flags/", data, format="json")

    def test_direct_patch_enable_is_gated(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.enable")
        flag = self._flag(active=False)

        response = self._patch(flag, {"active": True})

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        flag.refresh_from_db()
        assert flag.active is False
        self._assert_one_pending_zero_applied()

    def test_direct_patch_disable_is_gated(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.disable")
        flag = self._flag(active=True)

        response = self._patch(flag, {"active": False})

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        flag.refresh_from_db()
        assert flag.active is True
        self._assert_one_pending_zero_applied()

    def test_direct_patch_rollout_change_is_gated(self, _mock_enabled):
        _any_rollout_change_policy(self)
        flag = self._flag(active=True, rollout=20)

        response = self._patch(flag, {"filters": {"groups": [{"properties": [], "rollout_percentage": 90}]}})

        assert response.status_code == 409
        flag.refresh_from_db()
        assert flag.filters["groups"][0]["rollout_percentage"] == 20
        self._assert_one_pending_zero_applied()

    def test_create_active_is_gated(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.enable")

        response = self._post(
            {"key": "born-active", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}}
        )

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        assert not FeatureFlag.objects.filter(team=self.team, key="born-active").exists()
        self._assert_one_pending_zero_applied()

    def test_delete_then_recreate_as_active_is_gated(self, _mock_enabled):
        # Soft-deleting a flag then re-creating it as active is just another create() — it must
        # not be a way to land a flag in a guarded state without approval.
        existing = self._flag(active=False, key="recreate-flag")
        self._patch(existing, {"deleted": True})
        existing.refresh_from_db()
        assert existing.deleted is True

        _enable_policy_for(self, "feature_flag.enable")

        response = self._post(
            {"key": "recreate-flag", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}}
        )

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        assert not FeatureFlag.objects.filter(team=self.team, key="recreate-flag", active=True, deleted=False).exists()
        self._assert_one_pending_zero_applied()


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestScheduledChangeBypassMatrix(FeatureFlagBypassMatrixBase):
    """Scheduled changes are gated at scheduling time (a pending CR is bound to the row); the
    Celery applier only applies once approved, and expires the CR if the fire window closes first.
    A gated scheduled change must therefore leave the flag untouched and the CR EXPIRED."""

    def _schedule(self, flag: FeatureFlag, payload: dict, scheduled_at: datetime) -> ScheduledChange:
        from products.approvals.backend.scheduled_changes import gate_scheduled_change

        return ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=scheduled_at,
            created_by=self.user,
            change_request=gate_scheduled_change(flag, payload, self.user),
        )

    def test_scheduled_enable_is_gated(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.enable")
        flag = self._flag(active=False)

        scheduled = self._schedule(
            flag, {"operation": "update_status", "value": True}, datetime.now(UTC) - timedelta(seconds=30)
        )
        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        flag.refresh_from_db()
        assert flag.active is False
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPLIED).count() == 0

    def test_scheduled_disable_is_gated(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.disable")
        flag = self._flag(active=True)

        scheduled = self._schedule(
            flag, {"operation": "update_status", "value": False}, datetime.now(UTC) - timedelta(seconds=30)
        )
        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        flag.refresh_from_db()
        assert flag.active is True
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED

    def test_scheduled_rollout_change_is_gated(self, _mock_enabled):
        _any_rollout_change_policy(self)
        flag = self._flag(active=False, key="sched-rollout")

        scheduled = self._schedule(
            flag,
            {
                "operation": "add_release_condition",
                "value": {
                    "groups": [
                        {
                            "variant": None,
                            "properties": [],
                            "rollout_percentage": 90,
                            "aggregation_group_type_index": None,
                        }
                    ],
                    "payloads": {},
                    "multivariate": None,
                },
            },
            timezone.now() - timedelta(seconds=30),
        )
        assert scheduled.change_request is not None
        assert scheduled.change_request.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        flag.refresh_from_db()
        rollouts = [g.get("rollout_percentage") for g in flag.filters.get("groups", [])]
        assert 90 not in rollouts
        scheduled.change_request.refresh_from_db()
        assert scheduled.change_request.state == ChangeRequestState.EXPIRED


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestExperimentBypassMatrix(APIBaseTest):
    """Experiment lifecycle transitions flip the linked flag through FeatureFlagSerializer, so each
    must pass through the gate: launch/resume (enable), pause (disable), ship_variant + variant
    rollout edits (update). A gated transition raises ApprovalRequired and leaves the flag untouched."""

    _METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def _request(self) -> Any:
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _policy(self, action_key: str) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _draft(self, key: str) -> Experiment:
        return self._service().create_experiment(
            name="Matrix",
            feature_flag_key=key,
            metrics=[self._METRIC],
            primary_metrics_ordered_uuids=["m1"],
            allow_unknown_events=True,
        )

    def _launched(self, key: str) -> Experiment:
        experiment = self._draft(key)
        self._service().launch_experiment(experiment, request=self._request())
        experiment.refresh_from_db()
        return experiment

    def _assert_pending_zero_applied(self) -> None:
        assert ChangeRequest.objects.filter(state=ChangeRequestState.PENDING).count() == 1
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPLIED).count() == 0

    def test_launch_is_gated(self, _mock_enabled):
        experiment = self._draft("m-launch")
        self._policy("feature_flag.enable")

        with self.assertRaises(ApprovalRequired):
            self._service().launch_experiment(experiment, request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        assert experiment.start_date is None
        self._assert_pending_zero_applied()

    def test_pause_is_gated(self, _mock_enabled):
        experiment = self._launched("m-pause")
        assert experiment.feature_flag.active is True
        self._policy("feature_flag.disable")

        with self.assertRaises(ApprovalRequired):
            self._service().pause_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is True
        self._assert_pending_zero_applied()

    def test_resume_is_gated(self, _mock_enabled):
        experiment = self._launched("m-resume")
        self._service().pause_experiment(experiment, request=self._request())
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        self._policy("feature_flag.enable")

        with self.assertRaises(ApprovalRequired):
            self._service().resume_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        self._assert_pending_zero_applied()

    def test_ship_variant_is_gated(self, _mock_enabled):
        experiment = self._launched("m-ship")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]
        self._policy("feature_flag.update")

        with self.assertRaises(ApprovalRequired):
            self._service().ship_variant(experiment, variant_key="test", request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        assert experiment.end_date is None
        self._assert_pending_zero_applied()

    def test_web_experiment_variant_rollout_edit_is_gated(self, _mock_enabled):
        # update_experiment() writes a variant/rollout change back through FeatureFlagSerializer.
        # It routes through feature_flag.update, raises ApprovalRequired, and leaves the flag's
        # variants untouched. The gated flag write runs OUTSIDE update_experiment's atomic block
        # (like ship_variant/launch/pause/resume), so the pending ChangeRequest the gate created
        # survives for an approver to act on.
        experiment = self._launched("m-web")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]
        self._policy("feature_flag.update")

        new_variants = [
            {"key": "control", "rollout_percentage": 10},
            {"key": "test", "rollout_percentage": 90},
        ]

        # Mirror the DRF serializer context the experiment viewset hands to update_experiment.
        context = {
            "request": self._request(),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
            "get_organization": lambda: self.organization,
        }

        with self.assertRaises(ApprovalRequired):
            self._service().update_experiment(
                experiment,
                {"parameters": {"feature_flag_variants": new_variants}, "update_feature_flag_params": True},
                serializer_context=context,
            )

        # Security invariant: the gated field is unchanged and nothing was applied.
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        # The gated flag write runs outside the atomic block, so the pending CR survives.
        self._assert_pending_zero_applied()


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestCopyBypassMatrix(APIBaseTest):
    """copy_flags routes through FeatureFlagSerializer create()/update(), so a copy that lands the
    destination flag in a guarded state must gate. The gate raises inside serializer.save(), which
    copy_flags surfaces as a per-project failure — the destination row is NOT made/mutated."""

    def setUp(self):
        super().setUp()
        from posthog.models import Team

        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)
        self.source_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="copy-matrix-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

    def _enable_policy(self, team: Any) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _copy(self, target_ids: list[int]) -> Any:
        return self.client.post(
            f"/api/organizations/{self.organization.id}/feature_flags/copy_flags",
            {
                "feature_flag_key": self.source_flag.key,
                "from_project": self.source_flag.team_id,
                "target_project_ids": target_ids,
            },
        )

    def test_copy_active_to_new_target_is_gated(self, _mock_enabled):
        self._enable_policy(self.team_2)

        response = self._copy([self.team_2.id])

        assert response.status_code == 200
        assert response.json()["success"] == []
        assert not FeatureFlag.objects.filter(team=self.team_2, key=self.source_flag.key).exists()

    def test_copy_onto_existing_active_target_is_gated(self, _mock_enabled):
        existing = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=self.source_flag.key,
            active=False,
            filters={"groups": [{"rollout_percentage": 0}]},
        )
        self._enable_policy(self.team_2)

        response = self._copy([self.team_2.id])

        assert response.status_code == 200
        assert response.json()["success"] == []
        existing.refresh_from_db()
        assert existing.active is False


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestBypassMatrixControls(FeatureFlagBypassMatrixBase):
    """Explicit controls: the gate must NOT fire where no policy guards the change, and an approved
    change must actually apply. These guard against over-gating and prove the apply path works."""

    def test_create_disabled_flag_under_enable_policy_succeeds(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.enable")

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-disabled", "active": False, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 201
        assert FeatureFlag.objects.filter(team=self.team, key="born-disabled", active=False).exists()
        assert ChangeRequest.objects.count() == 0

    def test_enable_without_policy_applies_normally(self, _mock_enabled):
        flag = self._flag(active=False)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"active": True}, format="json"
        )

        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.active is True
        assert ChangeRequest.objects.count() == 0

    def test_approving_pending_cr_applies_the_change(self, _mock_enabled):
        _enable_policy_for(self, "feature_flag.enable")
        flag = self._flag(active=False)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"active": True}, format="json"
        )
        assert response.status_code == 409
        cr = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        assert cr.state == ChangeRequestState.PENDING

        result = ChangeRequestService(cr, self.user).approve()
        assert result.status == "applied"

        flag.refresh_from_db()
        assert flag.active is True
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPLIED

    def test_scheduled_cr_past_window_is_expired_not_applied(self, _mock_enabled):
        from products.approvals.backend.scheduled_changes import gate_scheduled_change

        _enable_policy_for(self, "feature_flag.enable")
        flag = self._flag(active=False)

        payload = {"operation": "update_status", "value": True}
        scheduled = ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload=payload,
            scheduled_at=datetime.now(UTC) - timedelta(seconds=30),
            created_by=self.user,
            change_request=gate_scheduled_change(flag, payload, self.user),
        )
        cr = scheduled.change_request
        assert cr is not None
        assert cr.state == ChangeRequestState.PENDING

        process_scheduled_changes()

        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.EXPIRED
        flag.refresh_from_db()
        assert flag.active is False
