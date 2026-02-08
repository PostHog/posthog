from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.approvals.models import Approval, ApprovalDecision, ApprovalPolicy, ChangeRequest, ChangeRequestState
from posthog.models import User


class TestChangeRequestViewSet(APIBaseTest):
    def _create_change_request(self, **kwargs):
        defaults = {
            "team": self.team,
            "organization": self.organization,
            "created_by": self.user,
            "action_key": "feature_flag.enable",
            "resource_type": "feature_flag",
            "resource_id": "123",
            "state": ChangeRequestState.PENDING,
            "intent": {"gated_changes": {"active": True}},
            "intent_display": {"description": "Enable feature flag"},
            "policy_snapshot": {"quorum": 1, "users": [self.user.id], "allow_self_approve": True},
            "expires_at": timezone.now() + timedelta(days=7),
        }
        defaults.update(kwargs)
        return ChangeRequest.objects.create(**defaults)

    def test_list_change_requests(self):
        cr = self._create_change_request()
        response = self.client.get(f"/api/environments/{self.team.id}/change_requests/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(cr.id)

    def test_list_filters_by_state(self):
        pending = self._create_change_request(state=ChangeRequestState.PENDING)
        self._create_change_request(state=ChangeRequestState.APPLIED, resource_id="456")

        response = self.client.get(f"/api/environments/{self.team.id}/change_requests/?state=pending")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(pending.id)

    def test_list_filters_by_resource(self):
        cr = self._create_change_request(resource_type="feature_flag", resource_id="123")
        self._create_change_request(resource_type="feature_flag", resource_id="456")

        response = self.client.get(
            f"/api/environments/{self.team.id}/change_requests/?resource_type=feature_flag&resource_id=123"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(cr.id)

    def test_get_change_request(self):
        cr = self._create_change_request()
        response = self.client.get(f"/api/environments/{self.team.id}/change_requests/{cr.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(cr.id)
        assert response.json()["action_key"] == "feature_flag.enable"

    @patch("posthog.approvals.services.apply_change_request")
    def test_approve_success(self, mock_apply):
        mock_apply.return_value = type("obj", (object,), {"id": 123, "version": 1})()
        cr = self._create_change_request()

        response = self.client.post(
            f"/api/environments/{self.team.id}/change_requests/{cr.id}/approve/",
            {"reason": "Looks good"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "applied"
        assert Approval.objects.filter(change_request=cr, decision=ApprovalDecision.APPROVED).exists()

    def test_approve_already_voted(self):
        cr = self._create_change_request()
        Approval.objects.create(change_request=cr, created_by=self.user, decision=ApprovalDecision.APPROVED)

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/approve/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already voted" in response.json()["error"].lower()

    def test_approve_not_pending(self):
        cr = self._create_change_request(state=ChangeRequestState.APPLIED)

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/approve/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_reject_success(self):
        cr = self._create_change_request()

        response = self.client.post(
            f"/api/environments/{self.team.id}/change_requests/{cr.id}/reject/",
            {"reason": "Not ready for production"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "rejected"
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.REJECTED

    def test_reject_requires_reason(self):
        cr = self._create_change_request()

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/reject/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "reason" in response.json()["error"].lower()

    def test_reject_already_voted(self):
        cr = self._create_change_request()
        Approval.objects.create(change_request=cr, created_by=self.user, decision=ApprovalDecision.APPROVED)

        response = self.client.post(
            f"/api/environments/{self.team.id}/change_requests/{cr.id}/reject/",
            {"reason": "Changed my mind"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already voted" in response.json()["error"].lower()

    def test_cancel_success(self):
        cr = self._create_change_request()

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/cancel/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "canceled"
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.REJECTED

    def test_cancel_only_by_requester(self):
        other_user = User.objects.create(email="other@posthog.com")
        cr = self._create_change_request(created_by=other_user)

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/cancel/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cancel_not_pending(self):
        cr = self._create_change_request(state=ChangeRequestState.APPLIED)

        response = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/cancel/")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestApprovalPolicyViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = 8  # Admin level
        self.organization_membership.save()

    def test_list_policies(self):
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/approval_policies/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(policy.id)

    def test_create_policy(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/approval_policies/",
            {
                "action_key": "feature_flag.enable",
                "approver_config": {"quorum": 2, "users": [self.user.id]},
                "allow_self_approve": False,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["action_key"] == "feature_flag.enable"
        assert response.json()["approver_config"]["quorum"] == 2
        assert ApprovalPolicy.objects.filter(action_key="feature_flag.enable").exists()

    def test_update_policy(self):
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/approval_policies/{policy.id}/",
            {"approver_config": {"quorum": 2, "users": [self.user.id]}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        policy.refresh_from_db()
        assert policy.approver_config["quorum"] == 2

    def test_delete_policy(self):
        policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/approval_policies/{policy.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ApprovalPolicy.objects.filter(id=policy.id).exists()

    def test_filter_by_action_key(self):
        policy1 = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.delete",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/approval_policies/?action_key=feature_flag.enable"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(policy1.id)

    def test_filter_by_enabled(self):
        enabled = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            enabled=True,
            created_by=self.user,
        )
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.delete",
            approver_config={"quorum": 1, "users": [self.user.id]},
            enabled=False,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/approval_policies/?enabled=true")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == str(enabled.id)

    def test_create_duplicate_policy_returns_error(self):
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/approval_policies/",
            {
                "action_key": "feature_flag.enable",
                "approver_config": {"quorum": 2, "users": [self.user.id]},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in response.json()["detail"]

    def test_create_policy_with_nonexistent_bypass_role_returns_error(self):
        import uuid

        fake_role_id = str(uuid.uuid4())

        response = self.client.post(
            f"/api/environments/{self.team.id}/approval_policies/",
            {
                "action_key": "feature_flag.enable",
                "approver_config": {"quorum": 1, "users": [self.user.id]},
                "bypass_roles": [fake_role_id],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "do not exist" in str(response.json())
