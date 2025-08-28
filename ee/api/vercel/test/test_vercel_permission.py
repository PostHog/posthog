import json

import pytest
from unittest.mock import MagicMock

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from posthog.models import Organization, Team
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.vercel.test.base import VercelTestBase
from ee.api.vercel.vercel_permission import VercelPermission


class TestVercelPermission(VercelTestBase):
    def setUp(self):
        super().setUp()
        self.permission = VercelPermission()
        self.mock_view = MagicMock()
        self.mock_request = MagicMock()

    def test_has_permission_validates_auth_type(self):
        self.mock_view.action = "update"
        self.mock_view.vercel_supported_auth_types = {"update": ["user"]}
        self.mock_request.headers = {"X-Vercel-Auth": "user"}

        assert self.permission.has_permission(self.mock_request, self.mock_view) is True

    def test_has_permission_missing_auth_header(self):
        self.mock_view.action = "update"
        self.mock_request.headers = {}

        with pytest.raises(AuthenticationFailed) as exc_info:
            self.permission.has_permission(self.mock_request, self.mock_view)
        assert str(exc_info.value.detail) == "Missing X-Vercel-Auth header"

    def test_has_permission_invalid_auth_type(self):
        # Test with auth type not allowed for endpoint
        self.mock_view.action = "update"
        self.mock_view.vercel_supported_auth_types = {"update": ["user"]}
        self.mock_request.headers = {"X-Vercel-Auth": "system"}

        with pytest.raises(PermissionDenied) as exc_info:
            self.permission.has_permission(self.mock_request, self.mock_view)
        assert "Auth type 'system' not allowed for this endpoint" in str(exc_info.value.detail)
        assert "Supported types: user" in str(exc_info.value.detail)

    def test_has_object_permission_validates_installation_id_match(self):
        self.mock_view.kwargs = {"installation_id": "inst_123"}
        self.mock_request.auth = {"installation_id": "inst_123"}

        assert self.permission.has_object_permission(self.mock_request, self.mock_view, None) is True

    def test_has_object_permission_installation_id_mismatch(self):
        self.mock_view.kwargs = {"installation_id": "inst_123"}
        self.mock_request.auth = {"installation_id": "inst_456"}

        with pytest.raises(PermissionDenied) as exc_info:
            self.permission.has_object_permission(self.mock_request, self.mock_view, None)
        assert str(exc_info.value.detail) == "Installation ID mismatch"

    def test_has_object_permission_missing_installation_id_in_url(self):
        self.mock_view.kwargs = {}
        self.mock_request.auth = {"installation_id": "inst_123"}

        with pytest.raises(PermissionDenied) as exc_info:
            self.permission.has_object_permission(self.mock_request, self.mock_view, None)
        assert str(exc_info.value.detail) == "Missing installation_id"

    def test_has_object_permission_no_jwt_auth(self):
        self.mock_view.kwargs = {"installation_id": "inst_123"}
        self.mock_request.auth = None

        with pytest.raises(AuthenticationFailed) as exc_info:
            self.permission.has_object_permission(self.mock_request, self.mock_view, None)
        assert str(exc_info.value.detail) == "No valid JWT authentication found"

    def test_has_object_permission_parent_lookup_installation_id(self):
        self.mock_view.kwargs = {"parent_lookup_installation_id": "inst_123"}
        self.mock_request.auth = {"installation_id": "inst_123"}

        assert self.permission.has_object_permission(self.mock_request, self.mock_view, None) is True

    def test_get_supported_auth_types_default(self):
        self.mock_view.action = "list"
        if hasattr(self.mock_view, "vercel_supported_auth_types"):
            delattr(self.mock_view, "vercel_supported_auth_types")
        auth_types = self.permission._get_supported_auth_types(self.mock_view)
        assert auth_types == ["user", "system"]

    def test_get_supported_auth_types_custom(self):
        self.mock_view.action = "destroy"
        self.mock_view.vercel_supported_auth_types = {"destroy": ["user", "system"], "update": ["user"]}
        auth_types = self.permission._get_supported_auth_types(self.mock_view)
        assert auth_types == ["user", "system"]

    def test_auth_type_case_insensitive(self):
        self.mock_view.action = "update"
        self.mock_view.vercel_supported_auth_types = {"update": ["user"]}
        self.mock_request.headers = {"X-Vercel-Auth": "USER"}

        assert self.permission.has_permission(self.mock_request, self.mock_view) is True


class TestVercelPermissionIntegration(VercelTestBase):
    def test_update_installation_wrong_installation_id_in_jwt(self):
        # JWT has different installation_id than URL
        url = f"/api/vercel/v1/installations/{self.installation_id}/"
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(self._create_user_auth_payload(installation_id='inst_different'))}",
            "HTTP_X_VERCEL_AUTH": "user",
        }
        response = self.client.patch(
            url, data=json.dumps({"billingPlanId": "pro200"}), content_type="application/json", **headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_destroy_installation_wrong_installation_id_in_jwt(self):
        # JWT has different installation_id than URL
        url = f"/api/vercel/v1/installations/{self.installation_id}/"
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(self._create_user_auth_payload(installation_id='inst_different'))}",
            "HTTP_X_VERCEL_AUTH": "user",
        }
        response = self.client.delete(url, **headers)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_with_wrong_auth_type(self):
        # Try to update with system auth (only user auth is allowed)
        url = f"/api/vercel/v1/installations/{self.installation_id}/"
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(self._create_system_auth_payload())}",
            "HTTP_X_VERCEL_AUTH": "system",
        }
        response = self.client.patch(
            url, data=json.dumps({"billingPlanId": "pro200"}), content_type="application/json", **headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_retrieve_with_wrong_auth_type(self):
        # Try to retrieve with user auth (only system auth is allowed)
        url = f"/api/vercel/v1/installations/{self.installation_id}/"
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(self._create_user_auth_payload())}",
            "HTTP_X_VERCEL_AUTH": "user",
        }
        response = self.client.get(url, **headers)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_organization_access_denied(self):
        other_org = Organization.objects.create(name="Other Org")
        Team.objects.create(organization=other_org, name="Other Team")

        other_installation_id = "inst_987654321"
        OrganizationIntegration.objects.create(
            organization=other_org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=other_installation_id,
            config={"billing_plan_id": "free"},
            created_by=self.user,
        )

        url = f"/api/vercel/v1/installations/{other_installation_id}/"
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(self._create_user_auth_payload(installation_id=other_installation_id))}",
            "HTTP_X_VERCEL_AUTH": "user",
        }
        response = self.client.patch(
            url, data=json.dumps({"billingPlanId": "pro200"}), content_type="application/json", **headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
