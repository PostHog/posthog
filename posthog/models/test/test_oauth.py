from datetime import timedelta
from django.conf import settings
from django.test import TestCase
from django.db import IntegrityError
from freezegun import freeze_time
from posthog.models.oauth import OAuthApplication, OAuthGrant
from posthog.models import Organization, User
from django.utils import timezone


class TestOAuthModels(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create(email="test@example.com")

    def test_create_oauth_application(self):
        app = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
            user=self.user,
            organization=self.organization,
            algorithm="RS256",
        )
        self.assertEqual(app.name, "Test App")
        self.assertEqual(app.client_id, "test_client_id")
        self.assertEqual(app.algorithm, "RS256")

    @freeze_time("2024-01-01 00:00:00")
    def test_create_oauth_application_with_skip_authorization_fails(self):
        # Test that creating an application with skip_authorization=True raises an error
        with self.assertRaises(IntegrityError):
            OAuthApplication.objects.create(
                name="Invalid App",
                client_id="invalid_client_id",
                client_secret="invalid_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://localhost:8000/callback",
                user=self.user,
                organization=self.organization,
                algorithm="RS256",
                skip_authorization=True,  # This should trigger the constraint
            )

    def test_create_oauth_grant(self):
        app = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
            user=self.user,
            organization=self.organization,
            algorithm="RS256",
        )
        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="test_code",
            code_challenge="test_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=settings.OAUTH2_PROVIDER["AUTHORIZATION_CODE_EXPIRE_SECONDS"]),
        )
        self.assertEqual(grant.code, "test_code")
        self.assertEqual(grant.code_challenge_method, "S256")

    # Add similar tests for OAuthAccessToken, OAuthRefreshToken, and OAuthIDToken
