from django.contrib.admin import AdminSite

from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin, OAuthApplicationForm
from posthog.models.oauth import OAuthApplication
from posthog.test.base import BaseTest


class TestOAuthApplicationAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = OAuthApplicationAdmin(OAuthApplication, AdminSite())

    def test_list_filter_includes_provisioning_fields(self):
        assert "provisioning_active" in self.admin.list_filter
        assert "provisioning_auth_method" in self.admin.list_filter
        assert "provisioning_partner_type" in self.admin.list_filter

    def test_pkce_app_hides_hmac_signing_secret(self):
        app = OAuthApplication(
            provisioning_auth_method="pkce",
        )

        fieldsets = self.admin.get_fieldsets(request=None, obj=app)
        provisioning = next(fieldset for fieldset in fieldsets if fieldset[0] == "Provisioning")

        assert "provisioning_signing_secret" not in provisioning[1]["fields"]

    def test_hmac_app_shows_hmac_signing_secret(self):
        app = OAuthApplication(
            provisioning_auth_method="hmac",
        )

        fieldsets = self.admin.get_fieldsets(request=None, obj=app)
        provisioning = next(fieldset for fieldset in fieldsets if fieldset[0] == "Provisioning")

        assert "provisioning_signing_secret" in provisioning[1]["fields"]

    def test_form_marks_signing_secret_as_hmac_only(self):
        form = OAuthApplicationForm()

        assert "Only used for HMAC provisioning partners" in form.fields["provisioning_signing_secret"].help_text

    def test_form_uses_dropdowns_for_provisioning_fields(self):
        form = OAuthApplicationForm()

        assert form.fields["provisioning_auth_method"].widget.choices[1][0] == "pkce"
        assert form.fields["provisioning_partner_type"].widget.choices[1][0] == "wizard"

    def test_add_form_shows_provisioning_fieldset(self):
        fieldsets = self.admin.get_fieldsets(request=None, obj=None)

        provisioning = next(fieldset for fieldset in fieldsets if fieldset[0] == "Provisioning")
        assert "provisioning_auth_method" in provisioning[1]["fields"]
        assert "provisioning_partner_type" in provisioning[1]["fields"]
