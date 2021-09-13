import copy
import os
from typing import Dict, cast

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status
from social_core.exceptions import AuthFailed

from ee.api.test.base import APILicensedTest
from posthog.models import Organization, OrganizationMembership, Team, User

MOCK_SETTINGS = {
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

CURRENT_FOLDER = os.path.dirname(__file__)


@pytest.mark.saml_only
@pytest.mark.skip_on_multitenancy
class TestEEAuthenticationAPI(APILicensedTest):

    # SAML Metadata

    def test_can_get_saml_metadata(self):

        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        with self.settings(**MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue("/complete/saml/" in response.content.decode())

    def test_need_to_be_authenticated_to_get_saml_metadata(self):
        self.client.logout()

        with self.settings(**MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), self.unauthenticated_response())

    def test_only_admins_can_get_saml_metadata(self):
        with self.settings(**MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You need to be an administrator or owner to access this resource."),
        )

    # SAML

    def test_can_initiate_saml_flow(self):
        with self.settings(**MOCK_SETTINGS):
            response = self.client.get("/login/saml/?idp=posthog_custom")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        # Assert user is redirected to the IdP's login page
        location = response.headers["Location"]
        self.assertIn("https://idp.hogflix.io/saml?SAMLRequest=", location)

    @freeze_time("2021-08-25T22:09:14.252Z")  # Ensures the SAML time validation works
    def test_can_login_with_saml(self):
        self.client.logout()

        user = User.objects.create(email="engineering@posthog.com")

        with self.settings(**MOCK_SETTINGS):
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

        with self.settings(**MOCK_SETTINGS):
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
    def test_can_signup_on_whitelisted_domain_with_saml(self):
        self.client.logout()

        # Note the user is signed up to this organization (which is not the default one)
        organization = Organization.objects.create(name="New Co.", domain_whitelist=["posthog.com"])

        with self.settings(**MOCK_SETTINGS):
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

        with self.settings(**MOCK_SETTINGS):
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
        self.assertEqual(user.team, None)  # This org has no teams
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(
            cast(OrganizationMembership, user.organization_memberships.first()).level,
            OrganizationMembership.Level.MEMBER,
        )

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
        Organization.objects.create(name="Red Herring", domain_whitelist=["differentdomain.com"])  # red herring

        with self.settings(**MOCK_SETTINGS):
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

        with self.settings(**MOCK_SETTINGS):
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
        settings = cast(Dict, copy.deepcopy(MOCK_SETTINGS))

        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_first_name"] = "urn:oid:2.5.4.42"
        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_last_name"] = "urn:oid:2.5.4.4"
        settings["SOCIAL_AUTH_SAML_ENABLED_IDPS"]["posthog_custom"]["attr_email"] = "urn:oid:0.9.2342.19200300.100.1.3"

        self.client.logout()

        self.organization.domain_whitelist = ["posthog.com"]
        self.organization.save()

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
        settings = cast(Dict, copy.deepcopy(MOCK_SETTINGS))

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

        self.organization.domain_whitelist = ["posthog.com"]
        self.organization.save()

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

        self.organization.domain_whitelist = ["posthog.com"]
        self.organization.save()

        with self.settings(**MOCK_SETTINGS):
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
            with self.settings(**MOCK_SETTINGS):
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
        with self.settings(**MOCK_SETTINGS):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Forcing only SAML disables regular API password login
        with self.settings(**MOCK_SETTINGS, SAML_ENFORCED=True):
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "saml_enforced",
                "detail": "This instance only allows SAML login.",
                "attr": None,
            },
        )

        # Client is automatically redirected to SAML login
        with self.settings(**MOCK_SETTINGS, SAML_ENFORCED=True):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.headers["Location"], "/login/saml/?idp=posthog_custom")
