import uuid
from datetime import timedelta

from freezegun import freeze_time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.models import Organization, User
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthGrant,
    OAuthIDToken,
    OAuthRefreshToken,
    revoke_oauth_session,
)


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
        assert app.name == "Test App"
        assert app.client_id == "test_client_id"
        assert app.algorithm == "RS256"

    def _make_app(self, name: str, client_id: str, **overrides) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name=name,
            client_id=client_id,
            client_secret=f"{client_id}_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
            **overrides,
        )

    def test_oauth_application_scopes_defaults_to_empty_list(self):
        app = self._make_app("Scopes Default", "scopes_default_client")
        assert app.scopes == []
        app.refresh_from_db()
        assert app.scopes == []

    def test_oauth_application_scopes_persists_explicit_list(self):
        app = self._make_app(
            "Scopes Explicit",
            "scopes_explicit_client",
            scopes=["insight:read", "llm_gateway:read"],
        )
        app.refresh_from_db()
        assert app.scopes == ["insight:read", "llm_gateway:read"]

    def test_oauth_access_token_label_defaults_to_empty_string(self):
        app = self._make_app("Token Label Default", "token_label_default_client")
        token = OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token="default_label_token",
            expires=timezone.now() + timedelta(minutes=5),
        )
        assert token.label == ""
        token.refresh_from_db()
        assert token.label == ""

    def test_oauth_access_token_label_persists_explicit_value(self):
        app = self._make_app("Token Label Explicit", "token_label_explicit_client")
        token = OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token="labeled_token",
            expires=timezone.now() + timedelta(minutes=5),
            label="laptop-2026",
        )
        token.refresh_from_db()
        assert token.label == "laptop-2026"

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
        assert grant.code == "test_code"
        assert grant.code_challenge_method == "S256"

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
        assert grant.expires > timezone.now()

        with freeze_time(timezone.now() + timedelta(minutes=10)):
            assert grant.expires < timezone.now()

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
        assert app.redirect_uris == "https://example.com/callback"

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
        assert app.redirect_uris == redirect_uri

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
        assert "localhost" in app.redirect_uris
        assert "example.com" in app.redirect_uris

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

    def test_invalid_redirect_uri_scheme_http_non_loopback(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Redirect App",
                client_id="invalid_redirect_client_id",
                client_secret="invalid_redirect_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )

    valid_custom_scheme_uris = [
        ("simple custom scheme", "posthog-code://callback"),
        ("custom scheme with path", "myapp://oauth/callback"),
        ("reverse domain style", "com.posthog.code://oauth"),
        ("cursor scheme", "cursor://oauth"),
        ("vscode scheme", "vscode://oauth"),
    ]

    @parameterized.expand(valid_custom_scheme_uris)
    @override_settings(DEBUG=False)
    def test_can_create_application_with_custom_scheme_for_native_apps(self, _name, redirect_uri):
        app = OAuthApplication.objects.create(
            name=f"Native App {_name}",
            client_id=f"native_client_id_{_name}",
            client_secret=f"native_client_secret_{_name}",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=redirect_uri,
            organization=self.organization,
            algorithm="RS256",
        )
        assert app.redirect_uris == redirect_uri

    def test_custom_scheme_with_fragment_still_rejected(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Custom Scheme App",
                client_id="invalid_custom_scheme_client_id",
                client_secret="invalid_custom_scheme_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="myapp://callback#fragment",
                organization=self.organization,
                algorithm="RS256",
            )

    blocked_scheme_uris = [
        ("javascript", "javascript:alert(1)"),
        ("data", "data:text/html,<script>alert(1)</script>"),
        ("file", "file:///etc/passwd"),
        ("blob", "blob:http://example.com/1234"),
        ("vbscript", "vbscript:msgbox(1)"),
    ]

    @parameterized.expand(blocked_scheme_uris)
    def test_blocked_schemes_rejected(self, _name, malicious_uri):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Blocked Scheme App",
                client_id=f"blocked_scheme_client_id_{_name}",
                client_secret="blocked_scheme_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris=malicious_uri,
                organization=self.organization,
                algorithm="RS256",
            )

    @override_settings(DEBUG=False)
    def test_mixed_custom_scheme_and_https_redirect_uris(self):
        app = OAuthApplication.objects.create(
            name="Mixed Scheme App",
            client_id="mixed_scheme_client_id",
            client_secret="mixed_scheme_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback posthog-code://oauth http://localhost:3000/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        assert "posthog-code://" in app.redirect_uris
        assert "https://example.com" in app.redirect_uris
        assert "localhost" in app.redirect_uris

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
        app_id = app.id
        app.delete()
        assert not OAuthGrant.objects.filter(application_id=app_id).exists()

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

        assert app.organization == self.organization

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

        assert app in self.organization.oauth_applications.all()

        assert grant in self.user.oauth_grants.all()
        assert id_token in self.user.oauth_id_tokens.all()
        assert access_token in self.user.oauth_access_tokens.all()
        assert refresh_token in self.user.oauth_refresh_tokens.all()

    def test_get_allowed_schemes_extracts_schemes_from_redirect_uris(self):
        app = OAuthApplication.objects.create(
            name="Multi Scheme App",
            client_id="multi_scheme_client_id",
            client_secret="multi_scheme_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback posthog-code://oauth http://localhost:3000/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        schemes = app.get_allowed_schemes()
        assert "https" in schemes
        assert "posthog-code" in schemes
        assert "http" in schemes
        assert len(schemes) == 3

    def test_get_allowed_schemes_filters_out_blocked_schemes(self):
        app = OAuthApplication.objects.create(
            name="Filtered Scheme App",
            client_id="filtered_scheme_client_id",
            client_secret="filtered_scheme_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        # Manually set redirect_uris to include blocked schemes
        # to test filtering (bypassing validation for test purposes)
        app.redirect_uris = "https://example.com/callback javascript:alert(1)"
        schemes = app.get_allowed_schemes()
        assert schemes == ["https"]
        assert "javascript" not in schemes

    def test_get_allowed_schemes_returns_https_fallback_when_no_valid_schemes(self):
        app = OAuthApplication.objects.create(
            name="Fallback Scheme App",
            client_id="fallback_scheme_client_id",
            client_secret="fallback_scheme_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        # Manually set redirect_uris to empty to test fallback
        app.redirect_uris = ""
        schemes = app.get_allowed_schemes()
        assert schemes == ["https"]

    def test_revoke_oauth_session_revokes_all_tokens_for_user_and_application(self):
        app = OAuthApplication.objects.create(
            name="Revoke Test App",
            client_id="revoke_test_client_id",
            client_secret="revoke_test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        access_token = OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token="access_token_1",
            expires=timezone.now() + timedelta(minutes=5),
        )
        OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token="access_token_2",
            expires=timezone.now() + timedelta(minutes=5),
        )
        refresh_token = OAuthRefreshToken.objects.create(
            application=app,
            user=self.user,
            token="refresh_token_1",
        )
        OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="grant_code",
            code_challenge="challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
        )

        revoke_oauth_session(access_token=access_token)

        assert OAuthAccessToken.objects.filter(user=self.user, application=app).count() == 0
        assert OAuthGrant.objects.filter(user=self.user, application=app).count() == 0
        refresh_token.refresh_from_db()
        assert refresh_token.revoked is not None

    def test_revoke_oauth_session_with_null_user_still_revokes_specific_token(self):
        app = OAuthApplication.objects.create(
            name="Null User Test App",
            client_id="null_user_client_id",
            client_secret="null_user_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        access_token = OAuthAccessToken.objects.create(
            application=app,
            user=None,
            token="null_user_access_token",
            expires=timezone.now() + timedelta(minutes=5),
        )
        token_id = access_token.id

        revoke_oauth_session(access_token=access_token)

        assert not OAuthAccessToken.objects.filter(id=token_id).exists()
