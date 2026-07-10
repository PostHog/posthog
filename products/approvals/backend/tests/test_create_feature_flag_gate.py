from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.approvals.backend.actions.feature_flags import (
    DisableFeatureFlagAction,
    EnableFeatureFlagAction,
    UpdateFeatureFlagAction,
)
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import ChangeRequestService
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestCreateDetection(APIBaseTest):
    """On a create, @approval_gate wraps FeatureFlagSerializer.create(self, validated_data),
    so there is no instance — args[0] is the validated change dict. Enable must fire when the
    new flag is born active; update must fire when its rollout meets a gated condition. Creating
    a disabled flag stays free, and disable never fires on a create."""

    def _serializer_view(self) -> MagicMock:
        view = MagicMock()
        view.context = {"request": MagicMock(), "get_team": lambda: self.team}
        return view

    def _post_request(self) -> MagicMock:
        request = MagicMock()
        request.method = "POST"
        request.data = {}
        return request

    def test_enable_detects_when_new_flag_born_active(self):
        view = self._serializer_view()
        # create() is called as create(self, validated_data) -> args = (validated_data,)
        result = EnableFeatureFlagAction.detect(self._post_request(), view, {"key": "f", "active": True})
        assert result is True

    def test_enable_does_not_fire_when_new_flag_disabled(self):
        view = self._serializer_view()
        result = EnableFeatureFlagAction.detect(self._post_request(), view, {"key": "f", "active": False})
        assert result is False

    def test_enable_fires_when_active_absent_on_create(self):
        # FeatureFlag.active defaults to True, so a create that omits `active` is still born
        # enabled — the gate must fire, otherwise the enable policy is trivially bypassed.
        view = self._serializer_view()
        result = EnableFeatureFlagAction.detect(self._post_request(), view, {"key": "f"})
        assert result is True

    def test_disable_never_fires_on_create(self):
        view = self._serializer_view()
        result = DisableFeatureFlagAction.detect(self._post_request(), view, {"key": "f", "active": False})
        assert result is False

    def test_update_detects_rollout_on_create(self):
        view = self._serializer_view()
        # Born at 100% trips an "any rollout change / >0" policy against an empty baseline.
        validated_data = {"key": "f", "get_filters": {"groups": [{"properties": [], "rollout_percentage": 100}]}}
        result = UpdateFeatureFlagAction.detect(self._post_request(), view, validated_data)
        assert result is True

    def test_update_does_not_fire_on_create_without_rollout(self):
        view = self._serializer_view()
        validated_data = {"key": "f", "get_filters": {"groups": [{"properties": []}]}}
        result = UpdateFeatureFlagAction.detect(self._post_request(), view, validated_data)
        assert result is False

    def test_enable_extract_intent_on_create_has_no_flag_id(self):
        view = self._serializer_view()
        intent = EnableFeatureFlagAction.extract_intent(self._post_request(), view, {"key": "f", "active": True})
        assert intent["flag_id"] is None
        assert intent["current_state"] == {"active": False}
        assert intent["gated_changes"] == {"active": True}
        assert intent["full_request_data"]["key"] == "f"

    def test_update_extract_intent_on_create_uses_empty_baseline(self):
        view = self._serializer_view()
        validated_data = {"key": "f", "get_filters": {"groups": [{"properties": [], "rollout_percentage": 100}]}}
        intent = UpdateFeatureFlagAction.extract_intent(self._post_request(), view, validated_data)
        assert intent["flag_id"] is None
        assert intent["current_state"]["rollout_percentage"] == []
        assert intent["gated_changes"]["rollout_percentage"][0]["value"] == 100
        assert intent["full_request_data"]["filters"]["groups"][0]["rollout_percentage"] == 100


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestCreateFlagGateAPI(APIBaseTest):
    """End-to-end: creating a flag that lands in a guarded state must require approval and NOT
    create the row until approved."""

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

    def test_create_active_flag_under_enable_policy_requires_approval(self, _mock_enabled):
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-active", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        assert not FeatureFlag.objects.filter(team=self.team, key="born-active").exists()

    def test_create_flag_without_active_under_enable_policy_requires_approval(self, _mock_enabled):
        # Omitting `active` lands the flag enabled (model default True), so the enable policy
        # must still gate it — the create must not slip through unapproved.
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-active-implicit", "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 409
        assert response.json().get("code") == "approval_required"
        assert not FeatureFlag.objects.filter(team=self.team, key="born-active-implicit").exists()

    def test_create_disabled_flag_under_enable_policy_succeeds(self, _mock_enabled):
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-disabled", "active": False, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 201
        assert FeatureFlag.objects.filter(team=self.team, key="born-disabled", active=False).exists()

    def test_create_active_flag_without_policy_succeeds(self, _mock_enabled):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "no-policy", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 201
        assert FeatureFlag.objects.filter(team=self.team, key="no-policy", active=True).exists()

    def test_approve_create_change_request_creates_flag_once(self, _mock_enabled):
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-active", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )
        assert response.status_code == 409
        cr_id = response.json()["change_request_id"]

        cr = ChangeRequest.objects.get(id=cr_id)
        assert cr.resource_id is None
        result = ChangeRequestService(cr, self.user).approve()
        assert result.status == "applied"

        flags = FeatureFlag.objects.filter(team=self.team, key="born-active")
        assert flags.count() == 1
        flag = flags.first()
        assert flag is not None
        assert flag.active is True
        assert flag.filters["groups"][0]["rollout_percentage"] == 100

    def test_create_rollout_gated_flag_requires_approval_then_applies(self, _mock_enabled):
        # any-change-from-baseline: a born-at-100% flag trips a >0 condition.
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "rollout-gated", "active": False, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )
        assert response.status_code == 409
        assert not FeatureFlag.objects.filter(team=self.team, key="rollout-gated").exists()

        cr = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        ChangeRequestService(cr, self.user).approve()

        flag = FeatureFlag.objects.get(team=self.team, key="rollout-gated")
        assert flag.filters["groups"][0]["rollout_percentage"] == 100

    def test_create_active_flag_with_rollout_under_both_policies_is_rejected(self, _mock_enabled):
        # A create that both enables the flag AND sets its rollout trips the enable policy and the
        # rollout-update policy at once. A single ChangeRequest carries one action's approval, and
        # the apply path replays the whole create payload — so gating on just the enable would let
        # the rollout change land unapproved. The gate must reject it (fail closed) and ask the
        # caller to split the change, creating neither the flag nor a partial ChangeRequest.
        self._enable_policy()
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-active-rollout", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )

        assert response.status_code == 400, response.content
        assert response.json().get("code") == "policy_conflict"
        assert not FeatureFlag.objects.filter(team=self.team, key="born-active-rollout").exists()
        assert ChangeRequest.objects.count() == 0

    def test_create_remote_config_flag_without_filters_requires_rollout_approval(self, _mock_enabled):
        # A remote-config create carries no `filters`; the serializer synthesizes a 100% rollout.
        # That default must be materialized before the gate runs, otherwise the create slips past
        # the rollout policy and lands a 100% rollout unapproved.
        self._update_policy({"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "remote-config-flag", "active": False, "is_remote_configuration": True},
            format="json",
        )

        assert response.status_code == 409, response.content
        assert response.json().get("code") == "approval_required"
        assert not FeatureFlag.objects.filter(team=self.team, key="remote-config-flag").exists()

        cr = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        ChangeRequestService(cr, self.user).approve()

        flag = FeatureFlag.objects.get(team=self.team, key="remote-config-flag")
        assert flag.filters["groups"][0]["rollout_percentage"] == 100

    def test_reapplying_create_change_request_does_not_duplicate(self, _mock_enabled):
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "born-active", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
            format="json",
        )
        cr = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        ChangeRequestService(cr, self.user).approve()
        assert FeatureFlag.objects.filter(team=self.team, key="born-active").count() == 1

        # Re-apply the already-applied CR: must not create a second row.
        from products.approvals.backend.services import apply_change_request

        cr.refresh_from_db()
        cr.state = ChangeRequestState.APPROVED
        cr.save()
        apply_change_request(cr)
        assert FeatureFlag.objects.filter(team=self.team, key="born-active").count() == 1
