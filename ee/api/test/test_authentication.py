import copy
import datetime
import os
import uuid
from typing import Dict, cast
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status
from social_core.exceptions import AuthFailed

from ee.api.test.base import APILicensedTest
from ee.models.license import License
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.organization_domain import OrganizationDomain

SAML_MOCK_SETTINGS = {
    "SOCIAL_AUTH_SAML_SP_ENTITY_ID": "http://localhost:8000",
    "SAML_CONFIGURED": True,
    "AUTHENTICATION_BACKENDS": settings.AUTHENTICATION_BACKENDS + ["social_core.backends.saml.SAMLAuth",],
    "SOCIAL_AUTH_SAML_ENABLED_IDPS": {
        "posthog_custom": {
            "entity_id": "http://www.okta.com/exk1ijlhixJxpyEBZ5d7",
            "url": "https://idp.hogflix.io/saml",
            "x509cert": """MIIDqDCCApCgAwIBAgIGAXtoc3o9MA0GCSqGSIb3DQEBCwUAMIGUMQswCQYDVQQGEwJVUzETMBEG
    A1UECAwKQ2FsaWZvcm5pYTEWMBQGA1UEBwwNU2FuIEZyYW5jaXNjbzENMAsGA1UECgwET2t0YTEU
    MBIGA1UECwwLU1NPUHJvdmlkZXIxFTATBgNVBAMMDGRldi0xMzU1NDU1NDEcMBoGCSqGSIb3DQEJ
    ARYNaW5mb0Bva3RhLmNvbTAeFw0yMTA4MjExMTIyMjNaFw0zMTA4MjExMTIzMjNaMIGUMQswCQYD
    VQQGEwJVUzETMBEGA1UECAwKQ2FsaWZvcm5pYTEWMBQGA1UEBwwNU2FuIEZyYW5jaXNjbzENMAsG
    A1UECgwET2t0YTEUMBIGA1UECwwLU1NPUHJvdmlkZXIxFTATBgNVBAMMDGRldi0xMzU1NDU1NDEc
    MBoGCSqGSIb3DQEJARYNaW5mb0Bva3RhLmNvbTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoC
    ggEBAMb1IcGzor7mGsGR0AsyzQaT0O9S1SVvdkG3z2duEU/I/a4fvaECm9xvVH7TY+RwwXcnkMst
    +ZZJVkTtnUGLn0oSbcwJ1iJwWNOctaNlaJtPDLvJTJpFB857D2tU01/zPn8UpBebX8tJSIcvnvyO
    Iblums97f9tlsI9GHqX5N1e1TxRg6FB2ba46mgb0EdzLtPxdYDVf8b5+V0EWp0fu5nbu5T4T+1Tq
    IVj2F1xwFTdsHnzh7FP92ohRRl8WQuC1BjAJTagGmgtfxQk2MW0Ti7Dl0Ejcwcjp7ezbyOgWLBmA
    fJ/Sg/MyEX11+4H+VQ8bGwIYtTM2Hc+W6gnhg4IdIfcCAwEAATANBgkqhkiG9w0BAQsFAAOCAQEA
    Ef8AeVm+rbrDqil8GwZz/6mTeSHeJgsYZhJqCsaVkRPe03+NO93fRt28vlDQoz9alzA1I1ikjmfB
    W/+x2dFPThR1/G4zGfF5pwU13gW1fse0/bO564f6LrmWYawL8SzwGbtelc9DxPN1X5g8Qk+j4DNm
    jSjV4Oxsv3ogajnnGYGv22iBgS1qccK/cg41YkpgfP36HbiwA10xjUMv5zs97Ljep4ejp6yoKrGL
    dcKmj4EG6bfcI3KY6wK46JoogXZdHDaFP+WOJNj/pJ165hYsYLcqkJktj/rEgGQmqAXWPOXHmFJb
    5FPleoJTchctnzUw+QfmSsLWQ838/lUQsN7FsQ==""",
            "attr_user_permanent_id": "name_id",
            "attr_first_name": "first_name",
            "attr_last_name": "last_name",
            "attr_email": "email",
        },
    },
    "SOCIAL_AUTH_SAML_SECURITY_CONFIG": {
        "wantAttributeStatement": False,  # already present in settings
        "allowSingleLabelDomains": True,  # to allow `http://testserver` in tests
    },
}

GOOGLE_MOCK_SETTINGS = {
    "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY": "google_key",
    "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET": "google_secret",
}

GITHUB_MOCK_SETTINGS = {
    "SOCIAL_AUTH_GITHUB_KEY": "github_key",
    "SOCIAL_AUTH_GITHUB_SECRET": "github_secret",
}

CURRENT_FOLDER = os.path.dirname(__file__)


class TestEELoginPrecheckAPI(APILicensedTest):
    CONFIG_AUTO_LOGIN = False

    def test_login_precheck_with_enforced_sso(self):
        OrganizationDomain.objects.create(
            domain="witw.app",
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="google-oauth2",
        )
        User.objects.create_and_join(self.organization, "spain@witw.app", self.CONFIG_PASSWORD)

        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post("/api/login/precheck", {"email": "spain@witw.app"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": "google-oauth2"})

    def test_login_precheck_with_unverified_domain(self):
        OrganizationDomain.objects.create(
            domain="witw.app",
            organization=self.organization,
            verified_at=None,  # note domain is not verified
            sso_enforcement="google-oauth2",
        )

        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post(
                "/api/login/precheck", {"email": "i_do_not_exist@witw.app"}
            )  # Note we didn't create a user that matches, only domain is matched
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None})

    def test_login_precheck_with_inexistent_account(self):
        OrganizationDomain.objects.create(
            domain="anotherdomain.com",
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="github",
        )
        User.objects.create_and_join(self.organization, "i_do_not_exist@anotherdomain.com", self.CONFIG_PASSWORD)

        with self.settings(**GITHUB_MOCK_SETTINGS):
            response = self.client.post("/api/login/precheck", {"email": "i_do_not_exist@anotherdomain.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": "github"})

    def test_login_precheck_with_enforced_sso_but_improperly_configured_sso(self):
        OrganizationDomain.objects.create(
            domain="witw.app",
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="google-oauth2",
        )
        User.objects.create_and_join(self.organization, "spain@witw.app", self.CONFIG_PASSWORD)

        response = self.client.post(
            "/api/login/precheck", {"email": "spain@witw.app"}
        )  # Note Google OAuth is not configured
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None})


class TestEEAuthenticationAPI(APILicensedTest):
    CONFIG_EMAIL = "user7@posthog.com"

    def create_enforced_domain(self, **kwargs) -> OrganizationDomain:
        return OrganizationDomain.objects.create(
            **{
                "domain": "posthog.com",
                "organization": self.organization,
                "verified_at": timezone.now(),
                "sso_enforcement": "google-oauth2",
                **kwargs,
            }
        )

    def test_can_enforce_sso(self):
        self.client.logout()

        # Can log in with password with SSO configured but not enforced
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Forcing SSO disables regular API password login
        self.create_enforced_domain()
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "sso_enforced",
                "detail": "You can only login with SSO for this account (google-oauth2).",
                "attr": None,
            },
        )

    def test_can_enforce_sso_on_cloud_enviroment(self):
        self.client.logout()
        License.objects.filter(pk=-1).delete()  # No instance licenses
        self.create_enforced_domain()
        self.organization.available_features = ["sso_enforcement"]
        self.organization.save()

        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "sso_enforced",
                "detail": "You can only login with SSO for this account (google-oauth2).",
                "attr": None,
            },
        )

    def test_cannot_reset_password_with_enforced_sso(self):
        self.create_enforced_domain()
        with self.settings(
            **GOOGLE_MOCK_SETTINGS, EMAIL_HOST="localhost", SITE_URL="https://my.posthog.net",
        ):
            response = self.client.post("/api/reset/", {"email": "i_dont_exist@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "sso_enforced",
                "detail": "Password reset is disabled because SSO login is enforced for this domain.",
                "attr": None,
            },
        )
        self.assertEqual(len(mail.outbox), 0)

    @patch("posthog.models.organization_domain.logger.warning")
    def test_cannot_enforce_sso_without_a_license(self, mock_warning):
        self.client.logout()
        self.license.valid_until = timezone.now() - datetime.timedelta(days=1)
        self.license.save()

        self.create_enforced_domain()

        # Enforcement is ignored
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Attempting to use SAML fails
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.get("/login/google-oauth2/")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/login?error_code=improperly_configured_sso", response.headers["Location"])

        # Ensure warning is properly logged for debugging
        mock_warning.assert_called_with(
            "🤑🚪 SSO is enforced for domain posthog.com but the organization does not have the proper license.",
            domain="posthog.com",
            organization=str(self.organization.id),
        )


@pytest.mark.skip_on_multitenancy
class TestEESAMLAuthenticationAPI(APILicensedTest):

    # SAML Metadata

    def test_can_get_saml_metadata(self):

        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue("/complete/saml/" in response.content.decode())

    def test_need_to_be_authenticated_to_get_saml_metadata(self):
        self.client.logout()

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), self.unauthenticated_response())

    def test_only_admins_can_get_saml_metadata(self):
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You need to be an administrator or owner to access this resource."),
        )

    # SAML

    def test_can_initiate_saml_flow(self):
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        # Assert user is redirected to the IdP's login page
        location = response.headers["Location"]
        self.assertIn("https://idp.hogflix.io/saml?SAMLRequest=", location)

    @freeze_time("2021-08-25T22:09:14.252Z")  # Ensures the SAML time validation works
    def test_can_login_with_saml(self):
        self.client.logout()

        user = User.objects.create(email="engineering@posthog.com", distinct_id=str(uuid.uuid4()))

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update(
            {"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6",}
        )
        _session.save()

        f = open(os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"), "r")
        saml_response = f.read()
        f.close()

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.post(
                "/complete/saml/",
                {"SAMLResponse": saml_response, "RelayState": "posthog_custom",},
                follow=True,
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")  # redirect to the home page

        # Ensure proper user was assigned
        _session = self.client.session
        self.assertEqual(_session.get("_auth_user_id"), str(user.pk))

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_can_signup_on_non_whitelisted_domain_with_saml(self):
        """
        SAML has automatic provisioning for any user who logs in, even if the domain whitelist does not match.
        """
        self.client.logout()

        organization = Organization.objects.create(name="Base Org")
        team = Team.objects.create(organization=organization, name="Base Team")
        Organization.objects.create(name="Red Herring")
        OrganizationDomain.objects.create(
            domain="anotherdomain.com",
            verified_at=timezone.now(),
            jit_provisioning_enabled=True,
            organization=organization,
        )  # red herring

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update(
            {"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6",}
        )
        _session.save()

        f = open(os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"), "r")
        saml_response = f.read()
        f.close()

        user_count = User.objects.count()

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.post(
                "/complete/saml/",
                {"SAMLResponse": saml_response, "RelayState": "posthog_custom",},
                format="multipart",
                follow=True,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")  # redirect to the home page

        # User is created
        self.assertEqual(User.objects.count(), user_count + 1)
        user = cast(User, User.objects.last())
        self.assertEqual(user.first_name, "PostHog")
        self.assertEqual(user.email, "engineering@posthog.com")
        self.assertEqual(user.organization, organization)
        self.assertEqual(user.team, team)
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(
            cast(OrganizationMembership, user.organization_memberships.first()).level,
            OrganizationMembership.Level.MEMBER,
        )

        _session = self.client.session
        self.assertEqual(_session.get("_auth_user_id"), str(user.pk))

    @freeze_time("2021-08-25T23:37:55.345Z")
    def test_can_configure_saml_assertion_attribute_names(self):
        settings = cast(Dict, copy.deepcopy(SAML_MOCK_SETTINGS))

        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_first_name"] = "urn:oid:2.5.4.42"
        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_last_name"] = "urn:oid:2.5.4.4"
        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_email"] = "urn:oid:0.9.2342.19200300.100.1.3"

        self.client.logout()

        with self.settings(**settings):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update(
            {"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6",}
        )
        _session.save()

        f = open(os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response_custom_attribute_names"), "r")
        saml_response = f.read()
        f.close()

        user_count = User.objects.count()

        with self.settings(**settings):
            response = self.client.post(
                "/complete/saml/",
                {"SAMLResponse": saml_response, "RelayState": "posthog_custom",},
                format="multipart",
                follow=True,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")  # redirect to the home page

        # User is created
        self.assertEqual(User.objects.count(), user_count + 1)
        user = cast(User, User.objects.last())
        self.assertEqual(user.first_name, "PostHog")
        self.assertEqual(user.email, "engineering@posthog.com")
        self.assertEqual(user.organization, self.organization)
        self.assertEqual(user.team, self.team)
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(
            cast(OrganizationMembership, user.organization_memberships.first()).level,
            OrganizationMembership.Level.MEMBER,
        )

        _session = self.client.session
        self.assertEqual(_session.get("_auth_user_id"), str(user.pk))

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cannot_login_with_improperly_signed_payload(self):
        settings = cast(Dict, copy.deepcopy(SAML_MOCK_SETTINGS))

        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"][
            "x509cert"
        ] = """MIIDPjCCAiYCCQC864/0fftWQTANBgkqhkiG9w0BAQsFADBhMQswCQYDVQQGEwJV
UzELMAkGA1UECAwCVVMxCzAJBgNVBAcMAlVTMQswCQYDVQQKDAJVUzELMAkGA1UE
CwwCVVMxCzAJBgNVBAMMAlVTMREwDwYJKoZIhvcNAQkBFgJVUzAeFw0yMTA4MjYw
MDAxMzNaFw0zMTA4MjYwMDAxMzNaMGExCzAJBgNVBAYTAlVTMQswCQYDVQQIDAJV
UzELMAkGA1UEBwwCVVMxCzAJBgNVBAoMAlVTMQswCQYDVQQLDAJVUzELMAkGA1UE
AwwCVVMxETAPBgkqhkiG9w0BCQEWAlVTMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A
MIIBCgKCAQEA25s1++GpP9vcXKJ+SN/xdlvPYLir3yMZd/bRfolygQ4BbuzCbqKv
04AGzKfwV11HXxjtQAU/KDtXuVRa+3vZroWcK01GL1C1aH/x0Q2Wy4XZ8Ooi7NlF
MME6vbCIBmXuo4TNouE/VFTz6ntwDNopIdlGDq4M60tFeoT99eDD4OhoCSaIo0aH
2s14CzF0sec3W742yuMHCVyTDrxFzkjMel/CdoNzysvwrqvkGYtLYJn2GSUIoCpG
y6N5CaVkNpAinNSeHKP9qN/z9hSsDNgz0QuTwZ2BxfDWtwJmRJzdQ3Oeq6RlniNY
BBI71zpuQhPeAlyoBg0wG+2ikiCllGug7wIDAQABMA0GCSqGSIb3DQEBCwUAA4IB
AQB8ytXAmU4oYjANiEJVVO5LZUCx3OrY/P1OX73eoXi624yj7xvhaa7whlk1SSL/
2ks8NZNLBFJbUwShdpzR2X+7AlvsLHmodAMq2Oj5x8O+mFB/6DBl0r40NAAsuzVw
2shE4kRi4RXVB0KiyBuExry5YSVTUu8spG4/oTQYJNZFZoSfsHS2mTyprBqqca1j
yh4jGarFborxwACgg6fCiMbHVq8qlcSkRvSW03u89s3Y4mxhMX3F4AZb56ddyfMk
LERK8jfXCMVmWPTy830CtQaZX2AJyBwHG4ElP2BOZNbFAvGzrKaBmK2Ym/OJxkhx
YotAcSbU3p5bzd11wpyebYHB"""

        self.client.logout()

        with self.settings(**settings):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update(
            {"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6",}
        )
        _session.save()

        f = open(os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"), "r")
        saml_response = f.read()
        f.close()

        user_count = User.objects.count()

        with self.assertRaises(AuthFailed) as e:
            with self.settings(**settings):
                response = self.client.post(
                    "/complete/saml/",
                    {"SAMLResponse": saml_response, "RelayState": "posthog_custom",},
                    format="multipart",
                    follow=True,
                )

        self.assertIn("Signature validation failed. SAML Response rejected", str(e.exception))

        self.assertEqual(User.objects.count(), user_count)

    @freeze_time("2021-08-25T23:53:51.000Z")
    def test_cannot_create_account_without_first_name_in_payload(self):
        self.client.logout()

        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update(
            {"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6",}
        )
        _session.save()

        f = open(os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response_no_first_name"), "r")
        saml_response = f.read()
        f.close()

        user_count = User.objects.count()

        with self.assertRaises(ValidationError) as e:
            with self.settings(**SAML_MOCK_SETTINGS):
                response = self.client.post(
                    "/complete/saml/",
                    {"SAMLResponse": saml_response, "RelayState": "posthog_custom",},
                    format="multipart",
                    follow=True,
                )

        self.assertEqual(str(e.exception), "{'name': ['This field is required and was not provided by the IdP.']}")

        self.assertEqual(User.objects.count(), user_count)

    def test_saml_can_be_enforced(self):
        self.client.logout()

        # Can log in regularly with SAML configured
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Forcing only SAML disables regular API password login
        OrganizationDomain.objects.create(
            domain="posthog.com", organization=self.organization, verified_at=timezone.now(), sso_enforcement="saml"
        )
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "sso_enforced",
                "detail": "You can only login with SSO for this account (saml).",
                "attr": None,
            },
        )

        # Login precheck returns SAML info
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": "saml"})

    def test_cannot_use_saml_without_enterprise_license(self):
        self.client.logout()
        self.license.valid_until = timezone.now() - datetime.timedelta(days=1)
        self.license.save()

        # Enforcement is ignored
        with self.settings(**SAML_MOCK_SETTINGS, SSO_ENFORCEMENT="saml"):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Client is not redirected to SAML login (even though it's enforced), enforcement is ignored
        with self.settings(**SAML_MOCK_SETTINGS, SSO_ENFORCEMENT="saml"):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Attempting to use SAML fails
        with self.settings(**SAML_MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/login?error_code=improperly_configured_sso", response.headers["Location"])
