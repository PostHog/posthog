from unittest.mock import Mock, patch
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from posthog.auth import SessionAuthentication, PersonalAPIKeyAuthentication
from posthog.models import User, Organization
from posthog.permissions import MFARequiredPermission


class TestMFARequiredPermission(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = MFARequiredPermission()
        self.view = Mock(spec=APIView)

        self.user = User(id=1, email="test@example.com")
        self.organization = Organization(id=1, name="Test Org", enforce_2fa=True)

    def _create_request_with_auth(self, auth_class, user=None):
        request = self.factory.get("/")
        request.user = user or self.user
        request.successful_authenticator = auth_class()
        return request

    def test_permission_granted_for_non_session_auth(self):
        request = self._create_request_with_auth(PersonalAPIKeyAuthentication)
        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_for_unauthenticated_user(self):
        request = self._create_request_with_auth(SessionAuthentication, user=None)
        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_for_anonymous_user(self):
        user = Mock()
        user.is_authenticated = False
        request = self._create_request_with_auth(SessionAuthentication, user=user)
        self.assertTrue(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.is_impersonated_session")
    def test_permission_granted_for_impersonated_session(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_when_organization_does_not_enforce_2fa(self):
        org_no_2fa = Organization(id=2, name="No 2FA Org", enforce_2fa=False)
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=org_no_2fa):
            self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_when_no_organization(self):
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=None):
            self.assertTrue(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    def test_permission_denied_when_user_has_no_2fa_device(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertFalse(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    @patch("posthog.permissions.is_mfa_verified_in_session")
    def test_permission_denied_when_session_not_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = False
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertFalse(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    @patch("posthog.permissions.is_mfa_verified_in_session")
    def test_permission_granted_when_fully_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = True
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertTrue(self.permission.has_permission(request, self.view))

    def test_get_organization_from_view(self):
        self.view.organization = self.organization
        request = self._create_request_with_auth(SessionAuthentication)

        result = self.permission._get_organization(request, self.view, self.user)
        self.assertEqual(result, self.organization)

    def test_get_organization_from_user(self):
        self.user.organization = self.organization
        request = self._create_request_with_auth(SessionAuthentication)

        result = self.permission._get_organization(request, self.view, self.user)
        self.assertEqual(result, self.organization)

    def test_get_organization_returns_none_on_attribute_error(self):
        user_without_org = Mock()
        del user_without_org.organization
        request = self._create_request_with_auth(SessionAuthentication)

        result = self.permission._get_organization(request, self.view, user_without_org)
        self.assertIsNone(result)
