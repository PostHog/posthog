from datetime import timedelta
from typing import cast

from posthog.test.base import APIBaseTest

from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from posthog.api.id_jag import get_allowed_resources
from posthog.settings.utils import generate_rsa_private_key_pem

from ee.billing.access_token import BILLING_TOKEN_CLIENT_ID, billing_audience, mint_billing_access_token
from ee.billing.grants import EffectiveBillingGrants
from ee.models import License

_PRIVATE_KEY_PEM = generate_rsa_private_key_pem()
_PUBLIC_KEY = cast(
    RSAPublicKey, serialization.load_pem_private_key(_PRIVATE_KEY_PEM.encode(), password=None).public_key()
)
SITE = "https://us.posthog.test"
BILLING = "https://billing.posthog.test"


@override_settings(
    OIDC_RSA_PRIVATE_KEY=_PRIVATE_KEY_PEM,
    SITE_URL=SITE,
    BILLING_SERVICE_URL=BILLING + "/",
    BILLING_ACCESS_TOKEN_TTL_SECONDS=900,
)
class TestMintBillingAccessToken(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.license = License.objects.create(
            key="license-id::license-secret", plan="cloud", valid_until=timezone.now() + timedelta(days=30)
        )
        self.grants = EffectiveBillingGrants(
            sub=f"user:{self.user.distinct_id}",
            scope=["billing:read"],
            roles=["admin"],
            entitlements=["billing:full_access"],
            projects=[self.team.id],
        )

    def test_token_carries_the_rfc_claims_and_verifies_against_the_oidc_key(self):
        token = mint_billing_access_token(self.organization, self.grants, self.license)
        header = jwt.get_unverified_header(token)
        self.assertEqual(header["typ"], "at+jwt")
        self.assertEqual(header["alg"], "RS256")
        self.assertIn("kid", header)
        claims = jwt.decode(token, _PUBLIC_KEY, algorithms=["RS256"], audience=BILLING, issuer=SITE)
        self.assertEqual(claims["sub"], f"user:{self.user.distinct_id}")
        self.assertEqual(claims["client_id"], BILLING_TOKEN_CLIENT_ID)
        self.assertEqual(claims["scope"], "billing:read")
        self.assertEqual(claims["roles"], ["admin"])
        self.assertEqual(claims["entitlements"], ["billing:full_access"])
        self.assertEqual(claims["org_id"], str(self.organization.id))
        self.assertEqual(claims["organization_name"], self.organization.name)
        self.assertEqual(claims["projects"], [self.team.id])
        self.assertEqual(claims["license_id"], "license-id")
        self.assertEqual(claims["exp"] - claims["iat"], 900)
        self.assertNotIn("act", claims)
        for claim in ("jti", "iat", "exp"):
            self.assertIn(claim, claims)

    def test_whole_organization_grants_carry_null_projects(self):
        grants = EffectiveBillingGrants(sub="user:1", scope=["billing:read"], entitlements=["billing:member"])
        claims = jwt.decode(
            mint_billing_access_token(self.organization, grants, self.license),
            _PUBLIC_KEY,
            algorithms=["RS256"],
            audience=BILLING,
        )
        self.assertIsNone(claims["projects"])
        self.assertEqual(claims["roles"], [])

    def test_act_is_carried_when_given(self):
        claims = jwt.decode(
            mint_billing_access_token(self.organization, self.grants, self.license, act={"sub": "agent:max"}),
            _PUBLIC_KEY,
            algorithms=["RS256"],
            audience=BILLING,
        )
        self.assertEqual(claims["act"], {"sub": "agent:max"})

    def test_no_license_means_no_token(self):
        from rest_framework.exceptions import NotAuthenticated

        with self.assertRaises(NotAuthenticated):
            mint_billing_access_token(self.organization, self.grants, None)

    def test_audience_is_the_billing_service_without_trailing_slash(self):
        self.assertEqual(billing_audience(), BILLING)

    @override_settings(ID_JAG_ALLOWED_RESOURCES=[BILLING, "https://mcp.posthog.test"])
    def test_the_token_endpoint_never_accepts_billing_as_a_resource(self):
        self.assertNotIn(BILLING, get_allowed_resources())
        self.assertIn("https://mcp.posthog.test", get_allowed_resources())
