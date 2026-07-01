from datetime import timedelta

from freezegun import freeze_time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, User
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthGrant,
    OAuthRefreshToken,
    revoke_application_sessions,
    revoke_oauth_session,
)


class TestOAuthModels(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create(email="test@example.com")

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
        self.assertEqual(app.scopes, [])
        app.refresh_from_db()
        self.assertEqual(app.scopes, [])

    @parameterized.expand(
        [
            ("empty_scopes_broad", [], [], [], []),
            ("explicit_no_optional_all_required", ["insight:read"], [], ["insight:read"], ["insight:read"]),
            ("split", ["insight:read"], ["dashboard:read"], ["insight:read", "dashboard:read"], ["insight:read"]),
            (
                "overlap_deduped",
                ["insight:read", "dashboard:write"],
                ["dashboard:write", "experiment:read"],
                ["insight:read", "dashboard:write", "experiment:read"],
                ["insight:read", "dashboard:write"],
            ),
        ]
    )
    def test_ceiling_and_required_scope_properties(self, _name, scopes, optional, expected_ceiling, expected_required):
        app = self._make_app(f"Split {_name}", f"split_{_name}_client", scopes=scopes, optional_scopes=optional)
        self.assertEqual(app.ceiling_scopes, expected_ceiling)
        self.assertEqual(app.required_scopes, expected_required)

    @parameterized.expand(
        [
            ("optional_without_required", [], ["dashboard:read"], "optional_scopes"),
            ("wildcard_in_required", ["*"], ["dashboard:read"], "scopes"),
            ("identity_scope_in_required", ["openid", "insight:read"], ["dashboard:read"], "scopes"),
            ("identity_scope_in_optional", ["insight:read"], ["openid"], "optional_scopes"),
        ]
    )
    def test_scope_split_validation_rejects_invalid_configs(self, _name, scopes, optional, error_field):
        with self.assertRaises(ValidationError) as ctx:
            self._make_app(f"Invalid {_name}", f"invalid_{_name}_client", scopes=scopes, optional_scopes=optional)
        self.assertIn(error_field, ctx.exception.message_dict)

    def test_cimd_application_can_declare_optional_scopes(self):
        # CIMD partners declare the required/optional split in their metadata; both fields are
        # refreshed together, so the split is a first-class CIMD feature, not a forbidden one.
        app = self._make_app(
            "CIMD Split",
            "cimd_split_client",
            is_cimd_client=True,
            cimd_metadata_url="https://example.com/oauth-client",
            scopes=["insight:read"],
            optional_scopes=["dashboard:read"],
        )
        self.assertEqual(app.required_scopes, ["insight:read"])
        self.assertEqual(app.ceiling_scopes, ["insight:read", "dashboard:read"])

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
        ("authority-less native scheme", "com.example.app:/oauth"),
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
        self.assertEqual(app.redirect_uris, redirect_uri)

    @parameterized.expand(
        [
            ("authority form", "myapp://callback#fragment"),
            ("authority-less native", "com.example.app:/oauth#fragment"),
        ]
    )
    def test_custom_scheme_with_fragment_still_rejected(self, _name, redirect_uri):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="Invalid Custom Scheme App",
                client_id="invalid_custom_scheme_client_id",
                client_secret="invalid_custom_scheme_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris=redirect_uri,
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
        self.assertIn("posthog-code://", app.redirect_uris)
        self.assertIn("https://example.com", app.redirect_uris)
        self.assertIn("localhost", app.redirect_uris)

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

    def test_code_grant_application_requires_redirect_uri(self):
        with self.assertRaises(ValidationError):
            OAuthApplication.objects.create(
                name="No Redirect App",
                client_id="no_redirect_client_id",
                client_secret="no_redirect_client_secret",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="",
                organization=self.organization,
                algorithm="RS256",
            )

    def test_valid_allowed_origins_accepted(self):
        app = self._make_app(
            "Allowed Origins App",
            "allowed_origins_client",
            allowed_origins="https://app.example.com https://www.example.com",
        )
        self.assertIn("app.example.com", app.allowed_origins)

    @parameterized.expand(
        [
            ("non-https scheme", "http://app.example.com"),
            ("origin with path", "https://app.example.com/callback"),
        ]
    )
    def test_invalid_allowed_origins_rejected(self, _name, allowed_origins):
        with self.assertRaises(ValidationError):
            self._make_app("Bad Origin App", "bad_origin_client", allowed_origins=allowed_origins)

    def test_rs256_without_private_key_rejected(self):
        with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": ""}):
            with self.assertRaises(ValidationError):
                self._make_app("No Key App", "no_key_client")

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
        self.assertIn("https", schemes)
        self.assertIn("posthog-code", schemes)
        self.assertIn("http", schemes)
        self.assertEqual(len(schemes), 3)

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
        self.assertEqual(schemes, ["https"])
        self.assertNotIn("javascript", schemes)

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
        self.assertEqual(schemes, ["https"])

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

        self.assertEqual(OAuthAccessToken.objects.filter(user=self.user, application=app).count(), 0)
        self.assertEqual(OAuthGrant.objects.filter(user=self.user, application=app).count(), 0)
        refresh_token.refresh_from_db()
        self.assertIsNotNone(refresh_token.revoked)

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

        self.assertFalse(OAuthAccessToken.objects.filter(id=token_id).exists())

    @freeze_time("2026-01-01 00:00:00")
    def test_revoke_application_sessions_revokes_across_all_users_and_leaves_other_apps(self):
        app = self._make_app("Narrowed App", "narrowed_client_id")
        other_app = self._make_app("Other App", "other_client_id")
        other_user = User.objects.create(email="other@example.com")

        for owner, suffix in [(self.user, "a"), (other_user, "b")]:
            access_token = OAuthAccessToken.objects.create(
                application=app, user=owner, token=f"at_{suffix}", expires=timezone.now() + timedelta(minutes=5)
            )
            OAuthRefreshToken.objects.create(
                application=app, user=owner, token=f"rt_{suffix}", access_token=access_token
            )
            OAuthGrant.objects.create(
                application=app,
                user=owner,
                code=f"grant_{suffix}",
                code_challenge="challenge",
                code_challenge_method="S256",
                expires=timezone.now() + timedelta(minutes=5),
            )

        survivor = OAuthAccessToken.objects.create(
            application=other_app, user=self.user, token="at_survivor", expires=timezone.now() + timedelta(minutes=5)
        )

        revoke_application_sessions(app)

        self.assertEqual(OAuthAccessToken.objects.filter(application=app).count(), 0)
        self.assertEqual(OAuthGrant.objects.filter(application=app).count(), 0)
        self.assertEqual(OAuthRefreshToken.objects.filter(application=app, revoked__isnull=True).count(), 0)
        self.assertTrue(OAuthAccessToken.objects.filter(id=survivor.id).exists())

    @freeze_time("2026-01-01 00:00:00")
    def test_revoke_application_sessions_stamps_sessions_revoked_at(self):
        app = self._make_app("Stamped App", "stamped_client_id")
        other_app = self._make_app("Untouched App", "untouched_client_id")

        revoke_application_sessions(app)

        app.refresh_from_db()
        other_app.refresh_from_db()
        self.assertEqual(app.sessions_revoked_at, timezone.now())
        self.assertIsNone(other_app.sessions_revoked_at)
