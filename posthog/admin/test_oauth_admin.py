from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite

from parameterized import parameterized

from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin, OAuthApplicationForm
from posthog.models.oauth import OAuthApplication


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
