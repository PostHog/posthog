import os
from typing import cast

from django.conf import settings
from freezegun.api import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.models import User
from posthog.models.organization import OrganizationMembership

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
        "allowSingleLabelDomains": True,  # to allow `http://testServer` in tests
    },
}

CURRENT_FOLDER = os.path.dirname(__file__)


class TestEEAuthenticationAPI(APILicensedTest):

    # SAML Metadata

    def test_can_get_saml_metadata(self):

        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        with self.settings(**MOCK_SETTINGS):
            response = self.client.get("/api/saml/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue("http://testserver/complete/saml/" in response.content.decode())

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
