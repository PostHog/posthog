from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FLAG_CREATED_AT = datetime(2026, 1, 14, 9, 30, 0, tzinfo=UTC)
FLAG_LAST_CALLED_AT = datetime(2026, 2, 3, 17, 45, 12, tzinfo=UTC)


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestFeatureFlagRoundTripGate(APIBaseTest):
    def _rollout_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 0},
            approver_config={"quorum": 1, "users": [self.user.id]},
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

    def _evaluated_flag(self) -> FeatureFlag:
        # last_called_at must be non-null: a null one round-trips as JSON `null` and never
        # reaches the serializer as a datetime, so the flag has to look evaluated.
        return FeatureFlag.objects.create(
            team=self.team,
            key="round-trip-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 25}]},
            active=True,
            created_by=self.user,
            created_at=FLAG_CREATED_AT,
            last_called_at=FLAG_LAST_CALLED_AT,
        )

    def test_patching_whole_get_body_is_gated_not_an_error(self, _mock_enabled):
        self._rollout_policy()
        flag = self._evaluated_flag()

        get_response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        assert get_response.status_code == 200, get_response.content
        body = get_response.json()
        assert body["last_called_at"] is not None
        assert body["created_at"] is not None

        body["filters"]["groups"][0]["rollout_percentage"] = 75
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", body, format="json")

        assert response.status_code == 409, response.content
        assert response.json().get("code") == "approval_required"

        change_request = ChangeRequest.objects.get(
            team=self.team, action_key="feature_flag.update", state=ChangeRequestState.PENDING
        )
        assert change_request.resource_id == str(flag.id)

        flag.refresh_from_db()
        assert flag.filters["groups"][0]["rollout_percentage"] == 25
        assert flag.last_called_at == FLAG_LAST_CALLED_AT

    def test_creating_with_timestamp_fields_is_gated_not_an_error(self, _mock_enabled):
        self._enable_policy()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "round-trip-create",
                "active": True,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "created_at": FLAG_CREATED_AT.isoformat(),
                "last_called_at": FLAG_LAST_CALLED_AT.isoformat(),
            },
            format="json",
        )

        assert response.status_code == 409, response.content
        assert response.json().get("code") == "approval_required"

        change_request = ChangeRequest.objects.get(
            team=self.team, action_key="feature_flag.enable", state=ChangeRequestState.PENDING
        )
        assert change_request.resource_id is None

        assert not FeatureFlag.objects.filter(team=self.team, key="round-trip-create").exists()
