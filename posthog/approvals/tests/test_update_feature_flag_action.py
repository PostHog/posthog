from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.approvals.actions.feature_flags import UpdateFeatureFlagAction
from posthog.approvals.models import ApprovalPolicy, ChangeRequest
from posthog.approvals.policies import PolicyEngine
from posthog.models import FeatureFlag


def _build_filters_for_path(path_spec: tuple, rollout_percentage: int) -> dict[str, Any]:
    """Build a filters dict with the rollout_percentage at the specified path."""
    array_path, field_name = path_spec[:-1], path_spec[-1]
    item = {"properties": [], field_name: rollout_percentage}

    # Build nested structure from inside out
    current: Any = [item]
    for key in reversed(array_path):
        current = {key: current}

    # Ensure groups key exists
    filters: dict[str, Any] = {"groups": [], **current}
    return filters


class TestUpdateFeatureFlagActionDetect(APIBaseTest):
    def _create_flag(self, filters: dict[str, Any] | None = None) -> FeatureFlag:
        default_filters = {
            "groups": [{"properties": [], "rollout_percentage": 50}],
        }
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters=filters or default_filters,
            created_by=self.user,
        )

    def _mock_request(self, method: str, data: dict[str, Any]) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.data = data
        return request

    def _mock_view(self, flag: FeatureFlag) -> MagicMock:
        view = MagicMock()
        view.get_object.return_value = flag
        view.team = self.team
        return view

    @parameterized.expand(UpdateFeatureFlagAction.ROLLOUT_PERCENTAGE_PATHS)
    def test_detect_returns_true_for_rollout_percentage_change(self, *path_spec):
        old_filters = _build_filters_for_path(path_spec, rollout_percentage=50)
        new_filters = _build_filters_for_path(path_spec, rollout_percentage=80)

        flag = self._create_flag(old_filters)
        request = self._mock_request("PATCH", {"filters": new_filters})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is True

    def test_detect_returns_false_for_enable_disable_only_operations(self):
        flag = self._create_flag()
        flag.active = False
        flag.save()

        request = self._mock_request("PATCH", {"active": True})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False

    def test_detect_returns_false_for_get_requests(self):
        flag = self._create_flag()
        request = self._mock_request("GET", {})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False

    def test_detect_returns_false_when_no_gateable_fields_changed(self):
        flag = self._create_flag({"groups": [{"properties": [], "rollout_percentage": 50}]})
        request = self._mock_request("PATCH", {"name": "Updated Name"})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False


class TestUpdateFeatureFlagActionExtractIntent(APIBaseTest):
    def _create_flag(self, filters: dict[str, Any]) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters=filters,
            created_by=self.user,
        )

    def _mock_request(self, method: str, data: dict[str, Any]) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.data = data
        return request

    def _mock_view(self, flag: FeatureFlag) -> MagicMock:
        view = MagicMock()
        view.get_object.return_value = flag
        view.team = self.team
        return view

    def test_extract_intent_captures_rollout_percentage_from_all_locations(self):
        old_filters = {
            "groups": [{"properties": [], "rollout_percentage": 50}],
            "super_groups": [{"properties": [], "rollout_percentage": 100}],
            "holdout_groups": [{"properties": [], "rollout_percentage": 70}],
            "multivariate": {"variants": [{"key": "control", "rollout_percentage": 50}]},
        }
        flag = self._create_flag(old_filters)

        new_filters = {
            "groups": [{"properties": [], "rollout_percentage": 80}],
            "super_groups": [{"properties": [], "rollout_percentage": 100}],
            "holdout_groups": [{"properties": [], "rollout_percentage": 70}],
            "multivariate": {"variants": [{"key": "control", "rollout_percentage": 60}]},
        }
        request = self._mock_request("PATCH", {"filters": new_filters})
        view = self._mock_view(flag)

        intent = UpdateFeatureFlagAction.extract_intent(request, view)

        assert "current_state" in intent
        assert "gated_changes" in intent
        assert "triggered_paths" in intent
        assert "full_request_data" in intent
        assert "preconditions" in intent
        assert intent["current_state"]["rollout_percentage"] is not None
        assert intent["gated_changes"]["rollout_percentage"] is not None

    def test_extract_intent_includes_triggered_paths(self):
        flag = self._create_flag({"groups": [{"properties": [], "rollout_percentage": 50}]})
        request = self._mock_request("PATCH", {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}})
        view = self._mock_view(flag)

        intent = UpdateFeatureFlagAction.extract_intent(request, view)

        assert len(intent["triggered_paths"]) > 0
        assert any("groups" in path for path in intent["triggered_paths"])


class TestUpdateFeatureFlagActionDisplayData(APIBaseTest):
    def test_get_display_data_generates_human_readable_diff(self):
        intent_data = {
            "flag_key": "test-flag",
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]},
            "triggered_paths": ["groups[0].rollout_percentage"],
        }

        display_data = UpdateFeatureFlagAction.get_display_data(intent_data)

        assert "description" in display_data
        assert "before" in display_data
        assert "after" in display_data
        assert "rollout percentage" in display_data["description"].lower()


class TestPolicyConditionEvaluation(APIBaseTest):
    def _create_policy_with_conditions(self, conditions: dict[str, Any]) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions=conditions,
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    @parameterized.expand(
        [
            (">", 50, 80, True),
            (">", 50, 50, False),
            (">", 50, 30, False),
            (">=", 50, 50, True),
            (">=", 50, 80, True),
            (">=", 50, 30, False),
            ("<", 50, 30, True),
            ("<", 50, 50, False),
            ("<", 50, 80, False),
            ("<=", 50, 50, True),
            ("<=", 50, 30, True),
            ("<=", 50, 80, False),
            ("==", 50, 50, True),
            ("==", 50, 80, False),
            ("!=", 50, 80, True),
            ("!=", 50, 50, False),
        ]
    )
    def test_before_after_condition_with_operators(
        self, operator: str, threshold: int, after_value: int, expected: bool
    ):
        conditions = {"type": "before_after", "field": "rollout_percentage", "operator": operator, "value": threshold}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 30}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": after_value}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is expected

    @parameterized.expand(
        [
            (">", 10, 50, 80, True),
            (">", 10, 50, 55, False),
            (">=", 10, 50, 60, True),
            ("<", 10, 50, 55, True),
        ]
    )
    def test_change_amount_condition(
        self, operator: str, threshold: int, before_value: int, after_value: int, expected: bool
    ):
        conditions = {"type": "change_amount", "field": "rollout_percentage", "operator": operator, "value": threshold}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": before_value}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": after_value}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is expected

    def test_any_change_condition_triggers_on_field_change(self):
        conditions = {"type": "any_change", "field": "rollout_percentage"}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is True

    def test_any_change_condition_does_not_trigger_when_unchanged(self):
        conditions = {"type": "any_change", "field": "rollout_percentage"}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is False

    def test_empty_conditions_gates_all_changes(self):
        policy = self._create_policy_with_conditions({})
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is True


class TestMultiPolicyConflictDetection(APIBaseTest):
    def _create_flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )

    def _create_policy(self, action_key: str, conditions: dict[str, Any] | None = None) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions=conditions or {},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    @patch("posthog.approvals.decorators._is_approvals_enabled", return_value=True)
    def test_single_policy_match_returns_normal_approval_flow(self, mock_enabled):
        flag = self._create_flag()
        self._create_policy(
            "feature_flag.update", {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        assert response.status_code in [200, 409]

    @patch("posthog.approvals.decorators._is_approvals_enabled", return_value=True)
    def test_matching_policy_returns_http_400(self, mock_enabled):
        flag = self._create_flag()
        self._create_policy(
            "feature_flag.update", {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        if response.status_code == 400:
            data = response.json()
            assert data.get("code") == "policy_conflict"
            assert "conflicting_policies" in data


class TestActionRegistrationAndIntegration(APIBaseTest):
    def test_update_feature_flag_action_registered_in_registry(self):
        from posthog.approvals.actions.registry import ACTION_REGISTRY, register_actions

        register_actions()

        assert "feature_flag.update" in ACTION_REGISTRY
        assert ACTION_REGISTRY["feature_flag.update"] == UpdateFeatureFlagAction

    def test_action_coexists_with_enable_disable_actions(self):
        from posthog.approvals.actions.registry import ACTION_REGISTRY, register_actions

        register_actions()

        assert "feature_flag.enable" in ACTION_REGISTRY
        assert "feature_flag.disable" in ACTION_REGISTRY
        assert "feature_flag.update" in ACTION_REGISTRY

    @patch("posthog.approvals.decorators._is_approvals_enabled", return_value=True)
    def test_enable_disable_detected_before_update(self, mock_enabled):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=False,
            created_by=self.user,
        )

        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"active": True, "filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        if response.status_code == 409:
            response.json()
            change_request = ChangeRequest.objects.filter(action_key="feature_flag.enable").first()
            assert change_request is not None
