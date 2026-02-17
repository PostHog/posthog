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
        user, auth = self.authentication.authenticate(request)
        self.assertTrue(user.is_authenticated)
        self.assertTrue(user.is_anonymous)
        self.assertIsNone(auth)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_invalid_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="wrong-secret"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_missing_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

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

            user, auth = self.authentication.authenticate(request)

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

        user, _ = self.authentication.authenticate(request)

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
            HTTP_X_INTERNAL_API_SECRET="test-secret-123",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Missing filters for which to get blast radius"})
