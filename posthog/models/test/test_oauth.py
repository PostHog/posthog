import uuid
from datetime import timedelta

from freezegun import freeze_time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.test.test_oauth import generate_rsa_key
from posthog.models import Organization, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthGrant, OAuthIDToken, OAuthRefreshToken


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        self.assertEqual(app.name, "Test App")
        self.assertEqual(app.client_id, "test_client_id")
        self.assertEqual(app.algorithm, "RS256")

    @freeze_time("2024-01-01 00:00:00")
    def test_create_oauth_application_with_skip_authorization_fails(self):
        # Test that creating an application with skip_authorization=True raises an error
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid App",
                client_id="invalid_client_id",
                client_secret="invalid_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
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
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="test_code",
            code_challenge="test_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=15),
        )
        self.assertEqual(grant.code, "test_code")
        self.assertEqual(grant.code_challenge_method, "S256")

    def test_token_expiry(self):
        app = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="test_code",
            code_challenge="test_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
            scoped_organizations=[self.organization.id],
        )
        self.assertTrue(grant.expires > timezone.now())

        with freeze_time(timezone.now() + timedelta(minutes=10)):
            self.assertTrue(grant.expires < timezone.now())

    def test_create_oauth_application_with_https_redirect_url(self):
        app = OAuthApplication.objects.create(
            name="Secure App",
            client_id="secure_client_id",
            client_secret="secure_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",  # HTTPS URL
            organization=self.organization,
            algorithm="RS256",
        )
        self.assertEqual(app.redirect_uris, "https://example.com/callback")

    @override_settings(DEBUG=False)
    def test_cannot_create_application_with_http_redirect_url_when_debug_is_false(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid App",
                client_id="invalid_client_id",
                client_secret="invalid_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    @override_settings(DEBUG=True)
    def test_can_create_application_with_http_redirect_url_when_debug_is_true(self):
        OAuthApplication.objects.create(
            name="Valid App",
            client_id="valid_client_id",
            client_secret="valid_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
            organization=self.organization,
            algorithm="RS256",
        )

    valid_loopback_uris = [
        ("localhost", "http://localhost:3000/callback"),
        ("127.0.0.1", "http://127.0.0.1:3000/callback"),
        ("127.0.0.2", "http://127.0.0.2:8000/callback"),
        ("127.0.1.1", "http://127.0.1.1:8000/callback"),
        ("127.255.255.255", "http://127.255.255.255:8000/callback"),
        ("localhost with https", "https://localhost:3000/callback"),
    ]

    @parameterized.expand(valid_loopback_uris)
    @override_settings(DEBUG=False)
    def test_can_create_application_with_loopback_address_in_production(self, _name, redirect_uri):
        app = OAuthApplication.objects.create(
            name=f"Loopback App {_name}",
            client_id=f"loopback_client_id_{_name}",
            client_secret=f"loopback_client_secret_{_name}",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=redirect_uri,
            organization=self.organization,
            algorithm="RS256",
        )
        self.assertEqual(app.redirect_uris, redirect_uri)

    malicious_localhost_domains = [
        ("subdomain of evil.com", "http://localhost.evil.com/callback"),
        ("127.0.0.1 subdomain of evil.com", "http://127.0.0.1.evil.com/callback"),
        ("fake localhost domain", "http://fake-localhost.com/callback"),
        ("127.0.0.1 subdomain of attacker.com", "http://127.0.0.1.attacker.com/callback"),
        ("mylocalhost domain", "http://mylocalhost.com/callback"),
    ]

    @parameterized.expand(malicious_localhost_domains)
    @override_settings(DEBUG=False)
    def test_cannot_create_application_with_malicious_localhost_domain_in_production(self, _name, malicious_uri):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Malicious App",
                client_id=f"malicious_client_id_{_name}",
                client_secret="malicious_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris=malicious_uri,
                organization=self.organization,
                algorithm="RS256",
            )

    @override_settings(DEBUG=False)
    def test_multiple_redirect_uris_with_mixed_localhost_and_production(self):
        app = OAuthApplication.objects.create(
            name="Mixed App",
            client_id="mixed_client_id",
            client_secret="mixed_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback http://localhost:3000/callback http://127.0.0.1:3000/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        self.assertIn("localhost", app.redirect_uris)
        self.assertIn("example.com", app.redirect_uris)

    def test_unique_client_id_constraint(self):
        OAuthApplication.objects.create(
            name="App One",
            client_id="unique_client_id",
            client_secret="client_secret_one",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="App Two",
                client_id="unique_client_id",  # Duplicate client ID
                client_secret="client_secret_two",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_invalid_redirect_uri_scheme(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Redirect App",
                client_id="invalid_redirect_client_id",
                client_secret="invalid_redirect_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="ftp://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_invalid_redirect_uri_fragment(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Redirect App",
                client_id="invalid_redirect_client_id",
                client_secret="invalid_redirect_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback#fragment",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_invalid_redirect_uri_no_host(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Redirect App",
                client_id="invalid_redirect_client_id",
                client_secret="invalid_redirect_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://:8000/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_unsupported_grant_type(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Unsupported Grant Type",
                client_id="unsupported_grant_type_client_id",
                client_secret="unsupported_grant_type_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_IMPLICIT,
                redirect_uris="https://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_token_revocation(self):
        app = OAuthApplication.objects.create(
            name="Revocable App",
            client_id="revocable_client_id",
            client_secret="revocable_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="revocable_code",
            code_challenge="revocable_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
        )
        grant.delete()
        with self.assertRaises(OAuthGrant.DoesNotExist):
            OAuthGrant.objects.get(code="revocable_code")

    def test_application_deletion_cascades(self):
        app = OAuthApplication.objects.create(
            name="Cascade Delete App",
            client_id="cascade_client_id",
            client_secret="cascade_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="cascade_code",
            code_challenge="cascade_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
        )
        app.delete()
        self.assertFalse(OAuthGrant.objects.filter(application=app).exists())

    def test_user_and_organization_association(self):
        app = OAuthApplication.objects.create(
            name="Association App",
            client_id="association_client_id",
            client_secret="association_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )

        self.assertEqual(app.organization, self.organization)

    def test_oauth_models_have_reverse_relationships(self):
        app = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )

        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="test_code",
            code_challenge="test_challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
        )

        id_token = OAuthIDToken.objects.create(
            application=app,
            user=self.user,
            jti=uuid.uuid4(),
            expires=timezone.now() + timedelta(minutes=5),
        )

        access_token = OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token="test_token",
            expires=timezone.now() + timedelta(minutes=5),
        )

        refresh_token = OAuthRefreshToken.objects.create(
            application=app,
            user=self.user,
            token="test_token",
        )

        self.assertIn(app, self.organization.oauth_applications.all())

        self.assertIn(grant, self.user.oauth_grants.all())
        self.assertIn(id_token, self.user.oauth_id_tokens.all())
        self.assertIn(access_token, self.user.oauth_access_tokens.all())
        self.assertIn(refresh_token, self.user.oauth_refresh_tokens.all())
