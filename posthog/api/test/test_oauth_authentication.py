from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.test.base import APIBaseTest


class TestOAuthAccessTokenAuthentication(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

        self.oauth_app = OAuthApplication.objects.create(
            name="Test App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="test_access_token_123",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )

    def test_authenticate_with_valid_oauth_token(self):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNotNone(result)
        user, token = result

        self.assertEqual(user, self.user)
        self.assertEqual(token, self.access_token)

    def test_authenticate_with_invalid_oauth_token(self):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": "Bearer invalid_token_123"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("Access token is invalid", str(context.exception))

    def test_authenticate_with_expired_oauth_token(self):
        expired_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="expired_token_123",
            expires=timezone.now() - timedelta(hours=1),
            scope="openid profile",
        )

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {expired_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("Access token has expired", str(context.exception))

    def test_authenticate_with_inactive_user(self):
        self.user.is_active = False
        self.user.save()

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("User associated with access token is disabled", str(context.exception))

    def test_authenticate_without_bearer_token(self):
        wsgi_request = self.factory.get("/")
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNone(result)

    @patch("posthog.auth.tag_queries")
    def test_authenticate_tags_queries_correctly(self, mock_tag_queries):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNotNone(result)

        mock_tag_queries.assert_called_once_with(
            user_id=self.user.pk,
            team_id=self.team.pk,
            access_method="oauth",
        )

    def test_authenticate_header_returns_correct_value(self):
        wsgi_request = self.factory.get("/")
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        header = authenticator.authenticate_header(request)

        self.assertEqual(header, "Bearer")
