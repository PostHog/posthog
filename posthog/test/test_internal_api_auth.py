from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, override_settings

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import InternalAPIAuthentication
from posthog.settings import LOCAL_DEV_INTERNAL_API_SECRET


class TestInternalAPIAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.authentication = InternalAPIAuthentication()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_valid_secret_allows_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="test-secret-123"))
        result = self.authentication.authenticate(request)
        assert result is not None
        user, auth = result
        self.assertTrue(user.is_authenticated)
        self.assertFalse(user.is_anonymous)
        self.assertIsNone(auth)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_invalid_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="wrong-secret"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_missing_secret_returns_none(self):
        # When the header is absent, the auth class signals "not my scheme" by
        # returning None (DRF convention). The view's permission classes
        # enforce IsAuthenticated and return 401 — see the endpoint-level
        # tests in test_internal_integration.py and test_internal_auth.py for
        # that side of the contract.
        request = Request(self.factory.get("/internal/endpoint"))
        self.assertIsNone(self.authentication.authenticate(request))

    @override_settings(INTERNAL_API_SECRET="")
    def test_no_configured_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="any-secret"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET=LOCAL_DEV_INTERNAL_API_SECRET, DEBUG=False, TEST=False)
    def test_local_dev_secret_denied_outside_debug_or_test(self):
        request = Request(
            self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET=LOCAL_DEV_INTERNAL_API_SECRET)
        )
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_team_and_organization_inferred_from_url_params(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="test-secret-123"))
        request.parser_context = {"kwargs": {"team_id": 123}}
        mocked_team = SimpleNamespace(id=123, organization_id="org-456")

        with patch("posthog.auth.apps.get_model") as mock_get_model:
            team_model = MagicMock()
            team_model.objects.only.return_value.get.return_value = mocked_team
            mock_get_model.return_value = team_model

            result = self.authentication.authenticate(request)

        assert result is not None
        user, auth = result
        self.assertEqual(user.current_team_id, mocked_team.id)
        self.assertEqual(user.current_organization_id, mocked_team.organization_id)
        self.assertIsNone(auth)

    def test_authenticate_header(self):
        request = self.factory.get("/internal/endpoint")
        self.assertEqual(self.authentication.authenticate_header(request), "InternalApiSecret")

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_sets_org_and_team_from_team_id_route_param(self):
        request = Request(
            self.factory.get(
                f"/api/projects/{self.team.id}/internal/hog_flows/user_blast_radius",
                HTTP_X_INTERNAL_API_SECRET="test-secret-123",
            ),
            parser_context={"kwargs": {"team_id": str(self.team.id)}},
        )

        result = self.authentication.authenticate(request)
        assert result is not None
        user, _ = result

        self.assertEqual(user.current_organization_id, self.organization.id)
        self.assertEqual(user.current_team_id, self.team.id)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_invalid_team_id_route_param_denies_access(self):
        request = Request(
            self.factory.get(
                "/api/projects/999999999/internal/hog_flows/user_blast_radius",
                HTTP_X_INTERNAL_API_SECRET="test-secret-123",
            ),
            parser_context={"kwargs": {"team_id": "999999999"}},
        )

        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_internal_hog_flow_endpoint_allows_internal_auth_without_user_membership(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/internal/hog_flows/user_blast_radius",
            {},
            format="json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Missing filters for which to get blast radius"})
