from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin, OAuthApplicationForm
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken


class TestOAuthApplicationAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = OAuthApplicationAdmin(OAuthApplication, AdminSite())

    def test_list_filter_includes_provisioning_fields(self):
        assert "provisioning_active" in self.admin.list_filter
        assert "provisioning_auth_method" in self.admin.list_filter
        assert "provisioning_partner_type" in self.admin.list_filter

    @parameterized.expand(
        [
            ("pkce", False),
            ("hmac", True),
        ]
    )
    def test_signing_secret_visibility(self, auth_method, expected_visible):
        app = OAuthApplication(provisioning_auth_method=auth_method)
        fieldsets = self.admin.get_fieldsets(request=None, obj=app)
        provisioning = next(fieldset for fieldset in fieldsets if fieldset[0] == "Provisioning")
        if expected_visible:
            assert "provisioning_signing_secret" in provisioning[1]["fields"]
        else:
            assert "provisioning_signing_secret" not in provisioning[1]["fields"]

    def test_form_marks_signing_secret_as_hmac_only(self):
        form = OAuthApplicationForm()

        assert "Only used for HMAC provisioning partners" in form.fields["provisioning_signing_secret"].help_text

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
