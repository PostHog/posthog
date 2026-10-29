from parameterized import parameterized

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.ratelimits import describe_budgets
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase, provisioning_config

LIMITS_URL = "/api/agentic/provisioning/limits"


class TestLimitsEndpoint(ProvisioningTestBase):
    def _self_registered_partner(self, *, switched_to_private_key_jwt: bool = False) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id="limits_public_partner",
            name="Limits Public Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL
            if switched_to_private_key_jwt
            else OAuthApplication.CLIENT_PUBLIC,
            jwks_uri="https://partner.example.com/.well-known/jwks.json" if switched_to_private_key_jwt else None,
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
        assert body["tier_basis"] == {"client_authentication": "private_key_jwt", "attested": False}
        # account_requests declares (5, 10); the JWKS tier multiplies by 5.
        assert body["endpoints"]["account_requests"]["per_hour"] == 50
        assert body["endpoints"]["account_requests"]["burst"] == 25
        # The exchange that minted this bearer spent one token, and peek must see it.
        exchanges = body["endpoints"]["token_exchanges"]
        assert exchanges["remaining"] == exchanges["burst"] - 1
        # Introspection charges its own bucket and reports it like any other endpoint.
        assert res["RateLimit-Limit"]

    def test_client_authenticated_partner_sees_its_overrides(self):
        self.partner.update_provisioning_rate_limits(resource_creates=7, deep_links=-1)

        res = self.client.post(LIMITS_URL, self._client_auth())

        assert res.status_code == 200
        body = res.json()
        assert body["endpoints"]["resource_creates"]["per_hour"] == 7
        assert body["endpoints"]["deep_links"] == {"unlimited": True}

    @parameterized.expand(
        [
            # A public partner's client_id is published, so honoring it would hand its
            # tier and live headroom to any caller, and charge its bucket to do it.
            ("bare_client_id", "post", True, False, 401),
            ("no_credentials", "post", False, False, 401),
            # GET has nowhere to carry client authentication, so the verb is gone. If it
            # comes back, the bare client_id path comes back with it.
            ("get_with_client_id", "get", True, False, 405),
            ("bare_client_id_of_a_private_key_jwt_partner", "post", True, True, 401),
        ]
    )
    def test_caller_without_proof_is_rejected(
        self, _name: str, method: str, name_a_partner: bool, switched_to_private_key_jwt: bool, expected: int
    ):
        partner = self._self_registered_partner(switched_to_private_key_jwt=switched_to_private_key_jwt)
        body = {"client_id": partner.client_id} if name_a_partner else {}

        res = getattr(self.client, method)(LIMITS_URL, body)

        assert res.status_code == expected

    @parameterized.expand(
        [
            ("deactivated", {"active": False}, False),
            ("dropped_its_private_key", {}, True),
        ]
    )
    def test_bearer_is_rejected_after_partner_changes(
        self, _name: str, change: dict[str, bool], drop_key: bool
    ) -> None:
        token = self._request_bearer_token().json()["access_token"]
        if change:
            self.partner.update_provisioning(**change)
        if drop_key:
            self.partner.jwks_uri = None
            self.partner.save(update_fields=["jwks_uri"])

        res = self.client.post(LIMITS_URL, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert res.status_code == 401

    def test_describe_budgets_marks_endpoints_the_tier_blocks(self):
        # Reported as blocked rather than as a budget, so a partner is not told it has
        # headroom on an endpoint its tier refuses outright.
        assert describe_budgets(self._self_registered_partner())["deep_links"] == {"blocked": True}
