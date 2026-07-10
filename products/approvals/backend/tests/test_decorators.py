from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestApprovalGateFailsClosed(APIBaseTest):
    """The gate must derive team/org from the serializer instance when the
    context lacks get_team/get_organization callables, instead of silently
    skipping the approval workflow (fail-closed, not fail-open)."""

    def _create_disabled_flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=False,
            created_by=self.user,
        )

    def _create_enable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _drf_request(self, data: dict[str, Any]) -> MagicMock:
        # detect()/extract_intent() read request.data, so the request must carry the payload.
        request = MagicMock()
        request.method = "PATCH"
        request.data = data
        request.user = self.user
        request.path = f"/api/projects/{self.team.id}/feature_flags/"
        return request

    def _serializer(self, flag: FeatureFlag, data: dict[str, Any], context: dict[str, Any]) -> FeatureFlagSerializer:
        serializer = FeatureFlagSerializer(instance=flag, data=data, partial=True, context=context)
        serializer.is_valid()
        return serializer

    def test_gate_blocks_when_context_lacks_org_and_team_callables(self, _mock_enabled):
        flag = self._create_disabled_flag()
        self._create_enable_policy()
        request = self._drf_request({"active": True})

        # Internal caller context: team_id present, but NO get_team/get_organization callables.
        serializer = self._serializer(
            flag,
            {"active": True},
            {"request": request, "team_id": self.team.id, "project_id": self.team.project_id},
        )

        with self.assertRaises(ApprovalRequired):
            serializer.save()

        flag.refresh_from_db()
        assert flag.active is False

    def test_gate_blocks_with_full_org_context(self, _mock_enabled):
        flag = self._create_disabled_flag()
        self._create_enable_policy()
        request = self._drf_request({"active": True})

        serializer = self._serializer(
            flag,
            {"active": True},
            {
                "request": request,
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "get_team": lambda: self.team,
                "get_organization": lambda: self.organization,
            },
        )

        with self.assertRaises(ApprovalRequired):
            serializer.save()

        flag.refresh_from_db()
        assert flag.active is False

    def test_gate_passes_through_when_no_policy(self, _mock_enabled):
        flag = self._create_disabled_flag()
        request = self._drf_request({"active": True})

        serializer = self._serializer(
            flag,
            {"active": True},
            {"request": request, "team_id": self.team.id, "project_id": self.team.project_id},
        )

        serializer.save()

        flag.refresh_from_db()
        assert flag.active is True
