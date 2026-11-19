from urllib.parse import parse_qs, urlsplit

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth.hashers import check_password
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin
from posthog.admin.console.oauth_tool import RevokeSessionsForm
from posthog.models.oauth import OAuthApplication


class TestOAuthApplicationAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = OAuthApplicationAdmin(OAuthApplication, AdminSite())

    def _change_form(self, app: OAuthApplication, **fields):
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

    @parameterized.expand(
        [
            ("signing_partner_made_public", {"can_create_accounts": True}, True, {"client_type": "public"}, True),
            ("signing_partner_drops_its_key", {"pays_for_customers": True}, True, {"jwks_uri": ""}, True),
            ("partner_without_signing_capabilities", {"can_provision_resources": True}, True, {"jwks_uri": ""}, False),
            # Never authenticates through provisioning auth, like the HMAC-signed Stripe Projects app.
            ("not_a_provisioning_partner", {"pays_for_customers": True}, False, {"jwks_uri": ""}, False),
            ("unrelated_edit", {"can_create_accounts": True}, True, {"name": "Renamed"}, False),
        ]
    )
    def test_an_edit_cannot_leave_a_signing_partner_without_a_key(
        self, name: str, config: dict, is_partner: bool, changes: dict, expects_error: bool
    ) -> None:
        app = OAuthApplication.objects.create(
            name=f"Signing App {name}",
            client_id=f"signing_client_id_{name}",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            jwks_uri="https://example.com/.well-known/jwks.json",
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=is_partner,
            _provisioning_config=config,
        )

        form = self._change_form(app, **{"jwks_uri": app.jwks_uri, **changes})

        assert form.is_valid() is not expects_error, form.errors
        assert ("client_type" in form.errors) is expects_error

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

    @parameterized.expand([("within_the_limit", 2, True), ("over_the_limit", 1, False)])
    def test_revoke_all_sessions_action_sends_the_picked_applications_to_the_console(
        self, _name: str, max_applications: int, expect_redirect: bool
    ):
        apps = [
            OAuthApplication.objects.create(
                name=f"Revoke action app {index}",
                client_id=f"revoke_action_client_id_{index}",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                organization=self.organization,
                algorithm="RS256",
            )
            for index in range(2)
        ]

        with (
            patch.object(RevokeSessionsForm, "MAX_APPLICATIONS", max_applications),
            patch.object(self.admin, "message_user") as message_user,
        ):
            response = self.admin.revoke_all_sessions(
                request=RequestFactory().post("/"),
                queryset=OAuthApplication.objects.filter(id__in=[app.id for app in apps]),
            )

        if not expect_redirect:
            self.assertIsNone(response)
            self.assertIn("1 applications or fewer", message_user.call_args.args[1])
            return
        message_user.assert_not_called()
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, "/admin/console/tools/oauth-sessions/revoke/")
        self.assertEqual(set(parse_qs(location.query)["application"]), {str(app.id) for app in apps})

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
        # An operator who could turn on is_cimd_client would hand the next metadata refresh
        # an app that no partner registered.
        app = OAuthApplication(is_cimd_client=False) if change else None
        request = RequestFactory().get("/")
        # A user without change permission gets an empty change form, which would pass this
        # assertion without proving anything.
        self.user.is_staff = True
        request.user = self.user
        form_class = self.admin.get_form(request, app, change=change)
        assert "name" in form_class.base_fields
        editable = [name for name in ("is_cimd_client", "is_dcr_client") if name in form_class.base_fields]
        assert editable == []
