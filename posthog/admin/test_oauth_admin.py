from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth.hashers import check_password
from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken


class TestOAuthApplicationAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = OAuthApplicationAdmin(OAuthApplication, AdminSite())

    def _provisioning_form(self, app: OAuthApplication, **fields):
        form_class = self.admin.get_form(RequestFactory().get("/"), app, change=True)
        data = {
            "name": app.name,
            "client_id": app.client_id,
            "client_type": app.client_type,
            "auth_brand": app.auth_brand,
            "authorization_grant_type": app.authorization_grant_type,
            "redirect_uris": app.redirect_uris,
            "algorithm": app.algorithm,
            **fields,
        }
        return form_class(data=data, instance=app)

    def test_admin_grants_a_capability_into_the_config(self):
        # Granting a capability is the admin's whole job here, and it writes into a JSONB blob
        # rather than a column, so a form that silently dropped it would look like it worked.
        app = OAuthApplication.objects.create(
            name="Capability App",
            client_id="capability_client_id",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )
        assert app.provisioning.can_use_github_grants is False

        form = self._provisioning_form(app, provisioning_can_use_github_grants="on")
        assert form.is_valid(), form.errors
        form.save()

        app.refresh_from_db()
        granted = app.provisioning
        assert granted.can_use_github_grants is True
        # Unticked boxes stay off rather than picking up a default.
        assert granted.can_start_wizard_runs is False

    def _rate_limit_app(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name="Rate Limit App",
            client_id="rate_limit_client_id",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )

    def test_admin_rate_limit_override_is_stored_per_endpoint(self):
        app = self._rate_limit_app()

        form = self._provisioning_form(app, provisioning_rate_limit_account_requests="250")
        assert form.is_valid(), form.errors
        form.save()

        app.refresh_from_db()
        assert app.provisioning.rate_limits == {"account_requests": 250}

    def test_admin_rate_limit_zero_is_rejected_and_minus_one_means_unlimited(self):
        # 0 used to mean unlimited; an operator typing it must get an error, not infinity.
        app = self._rate_limit_app()

        form = self._provisioning_form(app, provisioning_rate_limit_account_requests="0")
        assert not form.is_valid()
        assert "provisioning_rate_limit_account_requests" in form.errors

        form = self._provisioning_form(app, provisioning_rate_limit_account_requests="-1")
        assert form.is_valid(), form.errors
        form.save()
        app.refresh_from_db()
        assert app.provisioning.rate_limits == {"account_requests": -1}

    @parameterized.expand(
        [
            ("client_secret", OAuthApplication.CLIENT_CONFIDENTIAL, None, True),
            ("public", OAuthApplication.CLIENT_PUBLIC, None, False),
            # Confidential, but a jwks_uri means it authenticates by signed assertion, so a
            # secret would be inert while looking like working credentials to an operator.
            (
                "private_key_jwt",
                OAuthApplication.CLIENT_CONFIDENTIAL,
                "https://example.com/.well-known/jwks.json",
                False,
            ),
        ]
    )
    def test_regenerate_client_secret_action(self, name, client_type, jwks_uri, expects_secret):
        app = OAuthApplication.objects.create(
            name=f"Secret Action App {name}",
            client_id=f"secret_action_client_id_{name}",
            client_secret="",
            client_type=client_type,
            jwks_uri=jwks_uri,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )

        secret_before = app.client_secret

        request = RequestFactory().post("/")
        with patch.object(self.admin, "message_user") as message_user:
            self.admin.regenerate_client_secret(request=request, queryset=OAuthApplication.objects.filter(id=app.id))

        app.refresh_from_db()
        message = message_user.call_args.args[1]
        if not expects_secret:
            assert app.client_secret == secret_before
            assert "skipped" in message
            return

        # The plaintext is surfaced once in the admin message and only ever stored hashed, so
        # an operator who can't read it out of that message could never hand it to a partner.
        assert app.client_secret != secret_before
        plaintext = message.rsplit(": ", 1)[1]
        assert check_password(plaintext, app.client_secret)

    @freeze_time("2026-01-01 00:00:00")
    def test_revoke_all_sessions_action_force_invalidates_tokens(self):
        app = OAuthApplication.objects.create(
            name="Revoke Action App",
            client_id="revoke_action_client_id",
            client_secret="revoke_action_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        access_token = OAuthAccessToken.objects.create(
            application=app, user=self.user, token="at_revoke_action", expires=timezone.now() + timedelta(minutes=5)
        )
        OAuthRefreshToken.objects.create(
            application=app, user=self.user, token="rt_revoke_action", access_token=access_token
        )

        request = RequestFactory().post("/", {"confirm": "yes"})
        with patch.object(self.admin, "message_user") as message_user:
            self.admin.revoke_all_sessions(request=request, queryset=OAuthApplication.objects.filter(id=app.id))

        self.assertEqual(OAuthAccessToken.objects.filter(application=app).count(), 0)
        self.assertEqual(OAuthRefreshToken.objects.filter(application=app, revoked__isnull=True).count(), 0)
        message_user.assert_called_once()

    @freeze_time("2026-01-01 00:00:00")
    def test_revoke_all_sessions_without_confirm_renders_page_and_keeps_tokens(self):
        app = OAuthApplication.objects.create(
            name="Revoke Confirm App",
            client_id="revoke_confirm_client_id",
            client_secret="revoke_confirm_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        OAuthAccessToken.objects.create(
            application=app, user=self.user, token="at_revoke_confirm", expires=timezone.now() + timedelta(minutes=5)
        )

        self.user.is_staff = True
        request = RequestFactory().post("/")
        request.user = self.user
        response = self.admin.revoke_all_sessions(request=request, queryset=OAuthApplication.objects.filter(id=app.id))

        self.assertEqual(response.status_code, 200)
        self.assertIn("revoke_all_sessions_confirm.html", response.template_name)
        # Nothing revoked until the operator confirms.
        self.assertEqual(OAuthAccessToken.objects.filter(application=app).count(), 1)

    @parameterized.expand(
        [
            ("cimd_app", True, True),
            ("regular_app", False, False),
        ]
    )
    def test_scopes_readonly_only_for_cimd_apps(self, _name, is_cimd, expected_readonly):
        app = OAuthApplication(is_cimd_client=is_cimd)
        readonly = self.admin.get_readonly_fields(request=None, obj=app)
        assert ("scopes" in readonly) is expected_readonly

    @parameterized.expand(
        [
            ("cimd_url", "https://partner.example.com/.well-known/oauth-client-metadata", True),
            ("opaque", "IqK3fT9vBs2LwQ8xNc4Zr7Hd", False),
        ]
    )
    def test_new_app_cannot_take_a_cimd_shaped_client_id(self, _name, client_id, expects_error):
        # A metadata refresh writes the document's redirect URIs and auth settings onto the row
        # holding that URL. An operator who could type one here would point a partner's document
        # at an app registered by hand.
        request = RequestFactory().get("/")
        request.user = self.user
        form_class = self.admin.get_form(request, None, change=False)
        form = form_class(data={"name": "Manually registered app", "client_id": client_id})
        form.is_valid()
        assert ("client_id" in form.errors) is expects_error

    @parameterized.expand(
        [
            ("add_form", False),
            ("change_form", True),
        ]
    )
    def test_cimd_identity_fields_are_not_editable(self, _name, change):
        # An operator who could turn on is_cimd_client, or set a metadata URL, would hand the
        # next metadata refresh an app that no partner registered.
        app = OAuthApplication(is_cimd_client=False) if change else None
        request = RequestFactory().get("/")
        # A user without change permission gets an empty change form, which would pass this
        # assertion without proving anything.
        self.user.is_staff = True
        request.user = self.user
        form_class = self.admin.get_form(request, app, change=change)
        assert "name" in form_class.base_fields
        editable = [
            name for name in ("is_cimd_client", "is_dcr_client", "cimd_metadata_url") if name in form_class.base_fields
        ]
        assert editable == []
