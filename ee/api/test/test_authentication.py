import os

from django.conf import settings
from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.models.organization import OrganizationMembership

MOCK_SETTINGS = {
    "SOCIAL_AUTH_SAML_SP_ENTITY_ID": "https://playground.posthog.com",  # Needs to be overridden because SITE_URL is not set
    "SAML_CONFIGURED": True,
    "AUTHENTICATION_BACKENDS": settings.AUTHENTICATION_BACKENDS + ["social_core.backends.saml.SAMLAuth",],
    "SOCIAL_AUTH_SAML_ENABLED_IDPS": {
        "posthog_custom": {
            "entity_id": "https://playground.posthog.com",
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
