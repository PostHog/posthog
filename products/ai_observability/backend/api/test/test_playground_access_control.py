import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.ai_observability.backend.api.proxy import LLMProxyViewSet

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


COMPLETION_PAYLOAD = {
    "system": "",
    "messages": [{"role": "user", "content": "hello"}],
    "model": "gpt-5-mini",
    "provider": "openai",
}


@pytest.mark.ee
class TestPlaygroundAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=None,
            role=None,
        )

    def _login_with_playground_level(self, access_level: str) -> User:
        user = User.objects.create_and_join(self.organization, f"{access_level}@posthog.com", "testtest")
        user.current_team = self.team
        user.save()
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="llm_playground",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )
        self.client.force_login(user)
        return user

    def _post_completion(self):
        # Patched so the assertion is about the gate, not the payment-method check or the provider call
        with patch.object(LLMProxyViewSet, "_handle_completion_request", return_value=Response(status=200)):
            return self.client.post("/api/llm_proxy/completion/", COMPLETION_PAYLOAD)

    @parameterized.expand(
        [
            ("none", status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            ("viewer", status.HTTP_200_OK, status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_200_OK, status.HTTP_200_OK),
        ]
    )
    def test_access_level_gates_each_action(self, access_level, models_status, completion_status):
        self._login_with_playground_level(access_level)

        assert self.client.get("/api/llm_proxy/models/").status_code == models_status
        assert self._post_completion().status_code == completion_status

    def test_denied_without_a_current_team(self):
        user = self._login_with_playground_level("editor")
        user.current_team = None
        user.save()

        assert self._post_completion().status_code == status.HTTP_403_FORBIDDEN

    def test_org_admin_bypasses_a_project_default_of_none(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_playground",
            resource_id=None,
            access_level="none",
            organization_member=None,
            role=None,
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

        assert self._post_completion().status_code == status.HTTP_200_OK
