import datetime
import os
import uuid
from typing import cast
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.models import UserSocialAuth

from ee.api.test.base import APILicensedTest
from ee.models.license import License
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain
from ee.api.authentication import CustomGoogleOAuth2

SAML_MOCK_SETTINGS = {
    "SOCIAL_AUTH_SAML_SECURITY_CONFIG": {
        "wantAttributeStatement": False,  # already present in settings
        "allowSingleLabelDomains": True,  # to allow `http://testserver` in tests
    },
    "SITE_URL": "http://localhost:8000",  # http://localhost:8010 is now the default, but fixtures use 8000
}
SAML_MOCK_SETTINGS["SOCIAL_AUTH_SAML_SP_ENTITY_ID"] = SAML_MOCK_SETTINGS["SITE_URL"]

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
        self.assertEqual(
            response.json(),
            {"sso_enforcement": "google-oauth2", "saml_available": False},
        )

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
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": False})

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
        self.assertEqual(response.json(), {"sso_enforcement": "github", "saml_available": False})

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
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": False})


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
            response = self.client.post(
                "/api/login",
                {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Forcing SSO disables regular API password login
        self.create_enforced_domain()
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post(
                "/api/login",
                {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            )
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
        self.organization.available_product_features = [{"key": "sso_enforcement", "name": "sso_enforcement"}]
        self.organization.save()

        with self.settings(**GOOGLE_MOCK_SETTINGS):
            response = self.client.post(
                "/api/login",
                {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            )
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
            **GOOGLE_MOCK_SETTINGS,
            EMAIL_HOST="localhost",
            SITE_URL="https://my.posthog.net",
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
            response = self.client.post(
                "/api/login",
                {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            )
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

    def test_login_with_sso_resets_session(self):
        with self.settings(**GOOGLE_MOCK_SETTINGS):
            first_key = self.client.session.session_key
            self.client.post("/login/google-oauth2/", {})
            second_key = self.client.session.session_key
            self.assertNotEqual(first_key, second_key)


@pytest.mark.skip_on_multitenancy
@override_settings(**SAML_MOCK_SETTINGS)
class TestEESAMLAuthenticationAPI(APILicensedTest):
    CONFIG_AUTO_LOGIN = False
    organization_domain: OrganizationDomain = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.organization_domain = OrganizationDomain.objects.create(
            domain="posthog.com",
            verified_at=timezone.now(),
            organization=cls.organization,
            jit_provisioning_enabled=True,
            saml_entity_id="http://www.okta.com/exk1ijlhixJxpyEBZ5d7",
            saml_acs_url="https://idp.hogflix.io/saml",
            saml_x509_cert="""MIIDqDCCApCgAwIBAgIGAXtoc3o9MA0GCSqGSIb3DQEBCwUAMIGUMQswCQYDVQQGEwJVUzETMBEG
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
        )

    # SAML Metadata

    def test_can_get_saml_metadata(self):
        self.client.force_login(self.user)

        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue("/complete/saml/" in response.content.decode())

    def test_need_to_be_authenticated_to_get_saml_metadata(self):
        response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), self.unauthenticated_response())

    def test_only_admins_can_get_saml_metadata(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You need to be an administrator or owner to access this resource."),
        )

    # Login precheck

    def test_login_precheck_with_available_but_unenforced_saml(self):
        response = self.client.post(
            "/api/login/precheck", {"email": "helloworld@posthog.com"}
        )  # Note Google OAuth is not configured
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": True})

    # Initiate SAML flow

    def test_can_initiate_saml_flow(self):
        response = self.client.get("/login/saml/?email=hellohello@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        # Assert user is redirected to the IdP's login page
        location = response.headers["Location"]
        self.assertIn("https://idp.hogflix.io/saml?SAMLRequest=", location)

    def test_cannot_initiate_saml_flow_without_target_email_address(self):
        """
        We need the email address to know how to route the SAML request.
        """
        with self.assertRaises(AuthMissingParameter) as e:
            self.client.get("/login/saml/")

        self.assertEqual(str(e.exception), "Missing needed parameter email")

    def test_cannot_initiate_saml_flow_for_unconfigured_domain(self):
        """
        SAML settings have not been configured for the domain.
        """
        with self.assertRaises(AuthFailed) as e:
            self.client.get("/login/saml/?email=hellohello@gmail.com")

        self.assertEqual(
            str(e.exception),
            "Authentication failed: SAML not configured for this user.",
        )

    def test_cannot_initiate_saml_flow_for_unverified_domain(self):
        """
        Domain is unverified.
        """

        self.organization_domain.verified_at = None
        self.organization_domain.save()

        with self.assertRaises(AuthFailed) as e:
            self.client.get("/login/saml/?email=hellohello@gmail.com")

        self.assertEqual(
            str(e.exception),
            "Authentication failed: SAML not configured for this user.",
        )

    # Finish SAML flow (i.e. actual log in)

    @freeze_time("2021-08-25T22:09:14.252Z")  # Ensures the SAML timestamp validation passes
    def test_can_login_with_saml(self):
        user = User.objects.create(email="engineering@posthog.com", distinct_id=str(uuid.uuid4()))

        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        response = self.client.post(
            "/complete/saml/",
            {
                "SAMLResponse": saml_response,
                "RelayState": str(self.organization_domain.id),
            },
            follow=True,
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")  # redirect to the home page

        # Ensure proper user was assigned
        _session = self.client.session
        self.assertEqual(_session.get("_auth_user_id"), str(user.pk))

        # Test logged in request
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @freeze_time("2021-08-25T23:37:55.345Z")
    def test_saml_jit_provisioning_and_assertion_with_different_attribute_names(self):
        """
        Tests JIT provisioning for creating a user account on the fly.
        In addition, tests that the user can log in when the SAML response contains attribute names in one of their alternative forms.
        For example in this case we receive the user's first name at `urn:oid:2.5.4.42` instead of `first_name`.
        """

        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response_alt_attribute_names"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        user_count = User.objects.count()

        response = self.client.post(
            "/complete/saml/",
            {
                "SAMLResponse": saml_response,
                "RelayState": str(self.organization_domain.id),
            },
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

    @freeze_time("2021-08-25T23:37:55.345Z")
    def test_saml_jit_provisioning_with_case_insensitive_domain(self):
        """
        Tests that JIT provisioning works with case-insensitive domain matching.
        This verifies that users with email domains that differ only in case from
        the verified domain in the system can still be provisioned automatically.
        """

        # Create a new domain with uppercase characters
        original_domain = self.organization_domain.domain
        uppercase_email = f"engineering@{original_domain.upper()}"

        response = self.client.get(f"/login/saml/?email={uppercase_email}")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response_alt_attribute_names"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        user_count = User.objects.count()

        response = self.client.post(
            "/complete/saml/",
            {
                "SAMLResponse": saml_response,
                "RelayState": str(self.organization_domain.id),
            },
            format="multipart",
            follow=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")  # redirect to the home page

        # User is created despite the case difference in domain
        self.assertEqual(User.objects.count(), user_count + 1)
        user = cast(User, User.objects.last())
        self.assertEqual(user.email, uppercase_email.lower())  # The SSO middleware will make this lowercase
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
        self.organization_domain.saml_x509_cert = """MIIDPjCCAiYCCQC864/0fftWQTANBgkqhkiG9w0BAQsFADBhMQswCQYDVQQGEwJV
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
        self.organization_domain.save()

        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        user_count = User.objects.count()

        with self.assertRaises(AuthFailed) as e:
            response = self.client.post(
                "/complete/saml/",
                {
                    "SAMLResponse": saml_response,
                    "RelayState": str(self.organization_domain.id),
                },
                format="multipart",
                follow=True,
            )

        self.assertIn("Signature validation failed. SAML Response rejected", str(e.exception))

        self.assertEqual(User.objects.count(), user_count)

        # Test logged in request fails
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cannot_signup_with_saml_if_jit_provisioning_is_disabled(self):
        self.organization_domain.jit_provisioning_enabled = False
        self.organization_domain.save()

        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        user_count = User.objects.count()

        response = self.client.post(
            "/complete/saml/",
            {
                "SAMLResponse": saml_response,
                "RelayState": str(self.organization_domain.id),
            },
            format="multipart",
            follow=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/login?error_code=jit_not_enabled")  # show the appropriate login error

        # User is created
        self.assertEqual(User.objects.count(), user_count)

        # Test logged in request fails
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @freeze_time("2021-08-25T23:53:51.000Z")
    def test_cannot_create_account_without_first_name_in_payload(self):
        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response_no_first_name"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        user_count = User.objects.count()

        with self.assertRaises(ValidationError) as e:
            response = self.client.post(
                "/complete/saml/",
                {
                    "SAMLResponse": saml_response,
                    "RelayState": str(self.organization_domain.id),
                },
                format="multipart",
                follow=True,
            )

        self.assertEqual(
            str(e.exception),
            "{'name': ['This field is required and was not provided by the IdP.']}",
        )

        self.assertEqual(User.objects.count(), user_count)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cannot_login_with_saml_on_unverified_domain(self):
        User.objects.create(email="engineering@posthog.com", distinct_id=str(uuid.uuid4()))

        response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        # Note we "unverify" the domain after the initial request because we want to test the actual login process (not SAML initiation)
        self.organization_domain.verified_at = None
        self.organization_domain.save()

        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        with self.assertRaises(AuthFailed) as e:
            response = self.client.post(
                "/complete/saml/",
                {
                    "SAMLResponse": saml_response,
                    "RelayState": str(self.organization_domain.id),
                },
                follow=True,
                format="multipart",
            )

        self.assertEqual(
            str(e.exception),
            "Authentication failed: Authentication request is invalid. Invalid RelayState.",
        )

        # Assert user is not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_saml_can_be_enforced(self):
        User.objects.create_and_join(
            organization=self.organization,
            email="engineering@posthog.com",
            password=self.CONFIG_PASSWORD,
        )

        # Can log in regularly with SAML configured
        response = self.client.post(
            "/api/login",
            {"email": "engineering@posthog.com", "password": self.CONFIG_PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Forcing only SAML disables regular API password login
        self.organization_domain.sso_enforcement = "saml"
        self.organization_domain.save()
        response = self.client.post(
            "/api/login",
            {"email": "engineering@posthog.com", "password": self.CONFIG_PASSWORD},
        )
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
        response = self.client.post("/api/login/precheck", {"email": "engineering@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": "saml", "saml_available": True})

    def test_cannot_use_saml_without_enterprise_license(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.SSO_ENFORCEMENT, "name": AvailableFeature.SSO_ENFORCEMENT}
        ]
        self.organization.save()

        # Enforcement is ignored
        self.organization_domain.sso_enforcement = "saml"
        self.organization_domain.save()
        response = self.client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": False})

        # Cannot start SAML flow
        with self.assertRaises(AuthFailed) as e:
            response = self.client.get("/login/saml/?email=engineering@posthog.com")
        self.assertEqual(
            str(e.exception),
            "Authentication failed: Your organization does not have the required license to use SAML.",
        )

        # Attempting to use SAML fails
        _session = self.client.session
        _session.update({"saml_state": "ONELOGIN_87856a50b5490e643b1ebef9cb5bf6e78225a3c6"})
        _session.save()

        with open(
            os.path.join(CURRENT_FOLDER, "fixtures/saml_login_response"),
            encoding="utf_8",
        ) as f:
            saml_response = f.read()

        with self.assertRaises(AuthFailed) as e:
            response = self.client.post(
                "/complete/saml/",
                {
                    "SAMLResponse": saml_response,
                    "RelayState": str(self.organization_domain.id),
                },
                follow=True,
                format="multipart",
            )

        self.assertEqual(
            str(e.exception),
            "Authentication failed: Your organization does not have the required license to use SAML.",
        )

    # Remove after we figure out saml / xmlsec issues
    # Test login with SAML on dev prod before removing
    def test_xmlsec_and_lxml(self):
        import xmlsec
        import lxml

        assert "1.3.14" == xmlsec.__version__
        assert "5.2.1" == lxml.__version__


class TestCustomGoogleOAuth2(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.google_oauth = CustomGoogleOAuth2()
        self.details = {"email": "test@posthog.com"}
        self.sub = "google-oauth2|123456789"

    def test_auth_extra_arguments_without_email(self):
        """Test that auth_extra_arguments returns base arguments when no email is provided."""
        # Mock strategy to return empty GET parameters
        mock_request = type("MockRequest", (), {})()
        mock_request.GET = {}

        mock_strategy = type("MockStrategy", (), {})()
        mock_strategy.request = mock_request
        mock_strategy.setting = lambda name, default=None, backend=None: default

        self.google_oauth.strategy = mock_strategy

        extra_args = self.google_oauth.auth_extra_arguments()

        # Should only contain base arguments from parent class, no login_hint
        self.assertNotIn("login_hint", extra_args)

    def test_auth_extra_arguments_with_email(self):
        """Test that auth_extra_arguments adds login_hint when email is provided."""
        # Mock strategy to return email in GET parameters
        mock_request = type("MockRequest", (), {})()
        mock_request.GET = {"email": "test@posthog.com"}

        mock_strategy = type("MockStrategy", (), {})()
        mock_strategy.request = mock_request
        mock_strategy.setting = lambda name, default=None, backend=None: default

        self.google_oauth.strategy = mock_strategy

        extra_args = self.google_oauth.auth_extra_arguments()

        self.assertEqual(extra_args["login_hint"], "test@posthog.com")

    def test_get_user_id_existing_user_with_sub(self):
        """Test that a user with sub as uid continues using that sub."""
        # Create user with sub as uid
        UserSocialAuth.objects.create(provider="google-oauth2", uid=self.sub, user=self.user)

        response = {"email": "test@posthog.com", "sub": self.sub}

        uid = self.google_oauth.get_user_id(self.details, response)

        self.assertEqual(uid, self.sub)
        # Verify no migration occurred (count should be 1)
        self.assertEqual(UserSocialAuth.objects.filter(provider="google-oauth2").count(), 1)
        # Verify uid is still sub
        self.assertEqual(UserSocialAuth.objects.get(provider="google-oauth2").uid, self.sub)

    def test_get_user_id_migrates_email_to_sub(self):
        """Test that a user with email as uid gets migrated to using sub."""
        # Create user with email as uid (legacy format)
        social_auth = UserSocialAuth.objects.create(provider="google-oauth2", uid="test@posthog.com", user=self.user)

        response = {"email": "test@posthog.com", "sub": self.sub}

        uid = self.google_oauth.get_user_id(self.details, response)

        self.assertEqual(uid, self.sub)
        # Verify the uid was updated
        social_auth.refresh_from_db()
        self.assertEqual(social_auth.uid, self.sub)

    def test_get_user_id_new_user_uses_sub(self):
        """Test that a new user gets sub as uid."""
        response = {"email": "test@posthog.com", "sub": self.sub}

        uid = self.google_oauth.get_user_id(self.details, response)

        self.assertEqual(uid, self.sub)
        # Verify no UserSocialAuth objects were created
        self.assertEqual(UserSocialAuth.objects.filter(provider="google-oauth2").count(), 0)

    def test_get_user_id_missing_sub_raises_error(self):
        """Test that missing sub in response raises ValueError."""
        response = {
            "email": "test@posthog.com",
            # no sub provided
        }

        with self.assertRaises(ValueError) as e:
            self.google_oauth.get_user_id(self.details, response)

        self.assertEqual(str(e.exception), "Google OAuth response missing 'sub' claim")
