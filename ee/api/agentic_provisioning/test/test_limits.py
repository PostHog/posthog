from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.test.base import ProvisioningTestBase, provisioning_config


class TestLimitsEndpoint(ProvisioningTestBase):
    def test_bearer_partner_sees_tier_budgets_and_headroom(self):
        token = self._request_bearer_token().json()["access_token"]

        res = self.client.get("/api/agentic/provisioning/limits", HTTP_AUTHORIZATION=f"Bearer {token}")

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

    def test_public_partner_sees_blocked_and_overridden_endpoints(self):
        public = OAuthApplication.objects.create(
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
        public.update_provisioning_rate_limits(resource_creates=7, wizard_runs=-1)

        res = self.client.get(f"/api/agentic/provisioning/limits?client_id={public.client_id}")

        assert res.status_code == 200
        body = res.json()
        assert body["tier"] == "public"
        assert body["endpoints"]["deep_links"] == {"blocked": True}
        assert body["endpoints"]["resource_creates"]["per_hour"] == 7
        assert body["endpoints"]["wizard_runs"] == {"unlimited": True}

    def test_unauthenticated_caller_is_rejected(self):
        res = self.client.get("/api/agentic/provisioning/limits")
        assert res.status_code == 401
        assert res.json()["type"] == "error"
