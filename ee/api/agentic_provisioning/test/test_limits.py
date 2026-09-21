from parameterized import parameterized

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.ratelimits import describe_budgets
from ee.api.agentic_provisioning.test.base import TEST_PARTNER_CLIENT_SECRET, ProvisioningTestBase, provisioning_config

LIMITS_URL = "/api/agentic/provisioning/limits"


class TestLimitsEndpoint(ProvisioningTestBase):
    def _public_partner(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id="limits_public_partner",
            name="Limits Public Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(active=True),
        )

    def test_bearer_partner_sees_tier_budgets_and_headroom(self):
        token = self._request_bearer_token().json()["access_token"]

        res = self.client.post(LIMITS_URL, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert res.status_code == 200
        body = res.json()
        assert body["tier"] == "jwks"
        assert body["tier_basis"] == {"client_authentication": "client_secret_post", "attested": False}
        # account_requests declares (5, 10); the JWKS tier multiplies by 5.
        assert body["endpoints"]["account_requests"]["per_hour"] == 50
        assert body["endpoints"]["account_requests"]["burst"] == 25
        # The exchange that minted this bearer spent one token, and peek must see it.
        exchanges = body["endpoints"]["token_exchanges"]
        assert exchanges["remaining"] == exchanges["burst"] - 1
        # Introspection charges its own bucket and reports it like any other endpoint.
        assert res["RateLimit-Limit"]

    def test_client_authenticated_partner_sees_its_overrides(self):
        self.partner.update_provisioning_rate_limits(resource_creates=7, wizard_runs=-1)

        res = self.client.post(
            LIMITS_URL,
            {"client_id": self.partner.client_id, "client_secret": TEST_PARTNER_CLIENT_SECRET},
        )

        assert res.status_code == 200
        body = res.json()
        assert body["endpoints"]["resource_creates"]["per_hour"] == 7
        assert body["endpoints"]["wizard_runs"] == {"unlimited": True}

    @parameterized.expand(
        [
            # A public partner's client_id is published, so honoring it would hand its
            # tier and live headroom to any caller, and charge its bucket to do it.
            ("bare_client_id", "post", True, 401),
            ("no_credentials", "post", False, 401),
            # GET has nowhere to carry client authentication, so the verb is gone. If it
            # comes back, the bare client_id path comes back with it.
            ("get_with_client_id", "get", True, 405),
        ]
    )
    def test_caller_without_proof_is_rejected(self, _name: str, method: str, name_a_partner: bool, expected: int):
        public = self._public_partner()
        body = {"client_id": public.client_id} if name_a_partner else {}

        res = getattr(self.client, method)(LIMITS_URL, body)

        assert res.status_code == expected

    def test_deactivated_partner_bearer_is_rejected(self):
        token = self._request_bearer_token().json()["access_token"]
        self.partner.update_provisioning(active=False)

        res = self.client.post(LIMITS_URL, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert res.status_code == 401

    def test_describe_budgets_marks_endpoints_the_tier_blocks(self):
        # Reported as blocked rather than as a budget, so a partner is not told it has
        # headroom on an endpoint its tier refuses outright.
        assert describe_budgets(self._public_partner())["deep_links"] == {"blocked": True}
