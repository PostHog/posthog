from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

import jwt
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.organization import Organization
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.authentication import BillingServiceAuthentication
from ee.models import License


@patch("ee.api.authentication.get_cached_instance_license")
class TestVercelProxyAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.license_key = "test_license_id::test_license_secret"
        self.license = License.objects.create(key=self.license_key, plan="enterprise", valid_until=datetime.now(UTC))

        self.installation_id = "icfg_9bceb8ccT32d3U417ezb5c8p"
        self.vercel_access_token = "vercel_test_token_123"

        self.integration = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=self.installation_id,
            config={
                "billing_plan_id": "free",
                "scopes": ["read", "write"],
                "credentials": {"access_token": self.vercel_access_token, "token_type": "Bearer"},
            },
            created_by=self.user,
        )

        # Use unauthenticated client for these tests
        self.unauthenticated_client = APIClient()

    def _create_billing_service_token(
        self,
        organization_id: str | None = None,
        audience: str = BillingServiceAuthentication.EXPECTED_AUDIENCE,
        expired: bool = False,
    ) -> str:
        secret = self.license_key.split("::")[1]
        exp = datetime.now(UTC) + timedelta(minutes=-5 if expired else 15)

        payload = {
            "exp": exp,
            "aud": audience,
        }
        if organization_id is not None:
            payload["organization_id"] = organization_id

        return jwt.encode(payload, secret, algorithm="HS256")

    def _get_auth_headers(self, token: str | None = None) -> dict:
        if token is None:
            token = self._create_billing_service_token(organization_id=str(self.organization.id))
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @patch("ee.api.vercel.vercel_proxy.forward_to_vercel")
    def test_proxy_forwards_request_to_vercel(self, mock_forward, mock_license):
        mock_license.return_value = self.license

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"invoice_id": "inv_123"}
        mock_forward.return_value = mock_response

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {"amount": 100},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"invoice_id": "inv_123"}

        mock_forward.assert_called_once_with(
            config_id=self.installation_id,
            access_token=self.vercel_access_token,
            path="/billing/invoices",
            method="POST",
            body={"amount": 100},
        )

    @patch("ee.api.vercel.vercel_proxy.forward_to_vercel")
    def test_proxy_returns_vercel_error_status(self, mock_forward, mock_license):
        mock_license.return_value = self.license

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_response.json.return_value = {"error": "Invalid invoice data"}
        mock_forward.return_value = mock_response

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"error": "Invalid invoice data"}

    def test_proxy_rejects_missing_token(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
        )

        # DRF may return 401 or 403 depending on auth flow
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_proxy_rejects_expired_token(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_billing_service_token(organization_id=str(self.organization.id), expired=True)

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(token),
        )

        # DRF may return 401 or 403 depending on auth flow
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_proxy_rejects_wrong_audience(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_billing_service_token(
            organization_id=str(self.organization.id),
            audience="wrong:audience",
        )

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(token),
        )

        # DRF may return 401 or 403 depending on auth flow
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_proxy_rejects_missing_organization_id(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_billing_service_token(organization_id=None)

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(token),
        )

        # DRF may return 401 or 403 depending on auth flow
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_proxy_returns_404_when_no_vercel_integration(self, mock_license):
        mock_license.return_value = self.license

        other_org = Organization.objects.create(name="Other Org")
        token = self._create_billing_service_token(organization_id=str(other_org.id))

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(token),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"error": "No Vercel integration found for this organization"}

    def test_proxy_returns_500_when_no_access_token_in_config(self, mock_license):
        mock_license.return_value = self.license

        self.integration.config = {"credentials": {}}
        self.integration.save()

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"error": "Failed to retrieve Vercel credentials"}

    def test_proxy_validates_request_body(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "method" in response.json()

    def test_proxy_validates_http_method(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/invoices",
                "method": "INVALID",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "method" in response.json()

    def test_proxy_rejects_path_not_in_allowlist(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/some/other/path",
                "method": "POST",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "path" in response.json()
        assert "allowlist" in str(response.json()["path"])

    def test_proxy_rejects_path_traversal(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/../../../etc/passwd",
                "method": "GET",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "path" in response.json()

    def test_proxy_rejects_url_encoded_path_traversal(self, mock_license):
        mock_license.return_value = self.license

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {
                "path": "/billing/%2e%2e/%2e%2e/etc/passwd",
                "method": "GET",
                "body": {},
            },
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "path" in response.json()

    @patch("ee.api.vercel.vercel_proxy.forward_to_vercel")
    def test_proxy_handles_network_errors(self, mock_forward, mock_license):
        import requests as req

        mock_license.return_value = self.license
        mock_forward.side_effect = req.RequestException("Network error")

        response = self.unauthenticated_client.post(
            "/api/vercel/proxy/",
            {"path": "/billing/invoices", "method": "POST", "body": {}},
            format="json",
            **self._get_auth_headers(),
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"error": "Failed to reach Vercel API"}


@patch("ee.api.authentication.get_cached_instance_license")
class TestBillingServiceAuthentication(BaseTest):
    def setUp(self):
        super().setUp()
        self.license_key = "test_license_id::test_license_secret"
        self.license = License.objects.create(key=self.license_key, plan="enterprise", valid_until=datetime.now(UTC))
        self.auth = BillingServiceAuthentication()

    def _create_token(
        self,
        organization_id: str = "test-org-id",
        audience: str = BillingServiceAuthentication.EXPECTED_AUDIENCE,
        expired: bool = False,
        secret: str | None = None,
    ) -> str:
        if secret is None:
            secret = self.license_key.split("::")[1]

        exp = datetime.now(UTC) + timedelta(minutes=-5 if expired else 15)

        payload = {
            "exp": exp,
            "organization_id": organization_id,
            "aud": audience,
        }

        return jwt.encode(payload, secret, algorithm="HS256")

    def test_valid_token_authenticates(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_token(organization_id="org_123")
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}

        result = self.auth.authenticate(request)

        assert result is not None
        user, _ = result
        assert user.organization_id == "org_123"
        assert user.is_authenticated is True

    def test_expired_token_fails(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_token(expired=True)
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}

        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed) as context:
            self.auth.authenticate(request)

        assert "expired" in str(context.value.detail).lower()

    def test_wrong_audience_fails(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_token(audience="wrong:audience")
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}

        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed) as context:
            self.auth.authenticate(request)

        assert "audience" in str(context.value.detail).lower()

    def test_wrong_secret_fails(self, mock_license):
        mock_license.return_value = self.license

        token = self._create_token(secret="wrong_secret")
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}

        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_missing_token_fails(self, mock_license):
        mock_license.return_value = self.license

        request = MagicMock()
        request.headers = {}

        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed) as context:
            self.auth.authenticate(request)

        assert "missing" in str(context.value.detail).lower()

    def test_no_license_fails(self, mock_license):
        mock_license.return_value = None

        token = self._create_token()
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}

        from rest_framework.exceptions import AuthenticationFailed

        with pytest.raises(AuthenticationFailed) as context:
            self.auth.authenticate(request)

        assert "license" in str(context.value.detail).lower()
