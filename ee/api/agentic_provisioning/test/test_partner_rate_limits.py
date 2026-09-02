from datetime import timedelta
from urllib.parse import urlencode

from freezegun import freeze_time

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.oauth_provisioning import PartnerTier
from posthog.redis import TEST_clear_clients
from posthog.token_bucket import Budget, TEST_reset_scripts

from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import FLAT_MULTIPLIERS, charge_partner_by_name
from ee.api.agentic_provisioning.test.base import (
    TEST_PARTNER_CLIENT_SECRET,
    ProvisioningTestBase,
    patched_budget,
    provisioning_config,
)
from ee.api.agentic_provisioning.views.resources import RotateCredentialsView
from ee.api.agentic_provisioning.wizard import create_wizard_run

PARTNER_CLIENT_ID = "partner_rate_limit_test"

# account_requests declares Budget(burst=5, per_hour=10); the tier grid scales it.
ACCOUNT_REQUESTS_BURST_BY_TIER = {
    PartnerTier.PUBLIC: 5,
    PartnerTier.PUBLIC_ATTESTED: 10,
    PartnerTier.JWKS: 25,
    PartnerTier.JWKS_ATTESTED: 50,
}


class TestPartnerRateLimits(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        cache.clear()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)

        OAuthApplication.objects.filter(client_id=PARTNER_CLIENT_ID).delete()
        self.partner_app = OAuthApplication.objects.create(
            client_id=PARTNER_CLIENT_ID,
            name="Rate Limit Test Partner",
            client_secret=TEST_PARTNER_CLIENT_SECRET,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(
                active=True, can_create_accounts=True, can_provision_resources=True
            ),
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _get_partner_bearer_token(self) -> str:
        return self._request_bearer_token(partner=self.partner_app).json()["access_token"]

    def _partner_at_tier(self, tier: PartnerTier) -> OAuthApplication:
        confidential = tier in (PartnerTier.JWKS, PartnerTier.JWKS_ATTESTED)
        attested = tier in (PartnerTier.PUBLIC_ATTESTED, PartnerTier.JWKS_ATTESTED)
        return OAuthApplication.objects.create(
            client_id=f"tier_partner_{tier}",
            name=f"Tier partner {tier}",
            client_secret=TEST_PARTNER_CLIENT_SECRET if confidential else "",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL if confidential else OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
            organization=self.organization if attested else None,
            _provisioning_config=provisioning_config(active=True, can_create_accounts=True),
        )

    # --- Tier-scaled budgets ---

    @parameterized.expand([(tier.value, tier) for tier in PartnerTier])
    def test_tier_scales_the_budget(self, _name: str, tier: PartnerTier):
        partner = self._partner_at_tier(tier)
        assert partner.partner_tier == tier
        burst = ACCOUNT_REQUESTS_BURST_BY_TIER[tier]

        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(burst):
                charge_partner_by_name("account_requests", partner)

            with self.assertRaises(ProvisioningError) as ctx:
                charge_partner_by_name("account_requests", partner)
        assert ctx.exception.status == 429
        assert ctx.exception.retry_after is not None

    # --- Per-partner overrides ---

    def test_custom_override_replaces_the_computed_rate(self):
        # Override 3/hour on a declared 5-burst/10-per-hour budget scales the burst
        # to ceil(5 * 3/10) = 2, regardless of the partner's tier.
        self.partner_app.update_provisioning_rate_limits(account_requests=3)

        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(2):
                charge_partner_by_name("account_requests", self.partner_app)

            with self.assertRaises(ProvisioningError) as ctx:
                charge_partner_by_name("account_requests", self.partner_app)
        assert ctx.exception.status == 429
        assert ctx.exception.retry_after is not None

    def test_zero_override_disables_limiting(self):
        self.partner_app.update_provisioning_rate_limits(account_requests=0)

        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(100):
                charge_partner_by_name("account_requests", self.partner_app)

    def test_separate_buckets_per_endpoint(self):
        self.partner_app.update_provisioning_rate_limits(account_requests=1, resource_creates=1)
        with freeze_time("2026-01-01 00:00:00"):
            charge_partner_by_name("account_requests", self.partner_app)

            with self.assertRaises(ProvisioningError):
                charge_partner_by_name("account_requests", self.partner_app)
            charge_partner_by_name("resource_creates", self.partner_app)

    def test_separate_buckets_per_partner(self):
        other_partner = self._partner_at_tier(PartnerTier.JWKS)
        self.partner_app.update_provisioning_rate_limits(account_requests=1)
        other_partner.update_provisioning_rate_limits(account_requests=1)

        with freeze_time("2026-01-01 00:00:00"):
            charge_partner_by_name("account_requests", self.partner_app)

            with self.assertRaises(ProvisioningError):
                charge_partner_by_name("account_requests", self.partner_app)
            charge_partner_by_name("account_requests", other_partner)

    # --- Integration: token endpoint ---

    def test_token_exchange_auth_code_rate_limited(self):
        self.partner_app.update_provisioning_rate_limits(token_exchanges=1)

        # First exchange succeeds and spends the single-token bucket.
        self._get_partner_bearer_token()

        # Second exchange should be rate limited
        code, code_verifier = self._mint_auth_code(partner=self.partner_app)
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                **self._client_credentials(self.partner_app),
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )
        assert res.status_code == 429
        assert res["Retry-After"]

        # Auth code is consumed before the rate-limit check so a leaked code
        # can't be replayed to exhaust the bucket
        assert cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}") is None

    def test_refreshes_do_not_spend_the_exchange_bucket(self):
        # The split is what lets a partner keep more live tokens than its
        # hourly authorization budget: an exhausted exchange bucket must not
        # block refresh rotations.
        self.partner_app.update_provisioning_rate_limits(token_exchanges=1)
        self._get_partner_bearer_token()  # exhausts token_exchanges

        access_token = OAuthAccessToken.objects.create(
            application=self.partner_app,
            token="test_access_token",
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )
        OAuthRefreshToken.objects.create(
            application=self.partner_app,
            token="test_refresh_token_1",
            user=self.user,
            access_token=access_token,
            scoped_teams=[self.team.id],
        )

        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": "test_refresh_token_1",
                **self._client_credentials(self.partner_app),
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )
        assert res.status_code == 200

    # --- Integration: resource endpoints ---

    def test_resource_create_rate_limited_with_headers(self):
        token = self._get_partner_bearer_token()
        # Override 1/hour -> Budget(burst=1, per_hour=1), tier-independent.
        self.partner_app.update_provisioning_rate_limits(resource_creates=1)

        res = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=token)
        assert res.status_code == 200
        assert res["RateLimit-Limit"] == "1"
        assert res["RateLimit-Remaining"] == "0"

        res = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=token)
        assert res.status_code == 429
        assert res.json()["status"] == "error"
        assert res.json()["error"]["code"] == "rate_limited"
        assert res["Retry-After"]
        assert res["RateLimit-Remaining"] == "0"

    def test_rejected_request_is_refunded(self):
        # A request that provably did no work (validation failure) costs no
        # quota: with a burst of 1, a 400 followed by a valid request must not
        # 429 the valid one.
        token = self._get_partner_bearer_token()

        with patched_budget(
            RotateCredentialsView,
            "post",
            "credential_rotations",
            Budget(burst=1, per_hour=1),
            multipliers=FLAT_MULTIPLIERS,
        ):
            res = self._post_with_bearer(
                f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
                {"label_prefix": "x" * 100},
                token=token,
            )
            assert res.status_code == 400

            res = self._post_with_bearer(
                f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
                {},
                token=token,
            )
            assert res.status_code == 200

    # --- Tier gating ---

    def test_blocked_tier_cannot_use_deep_links(self):
        public_partner = self._partner_at_tier(PartnerTier.PUBLIC)
        with self.assertRaises(ProvisioningError) as ctx:
            charge_partner_by_name("deep_links", public_partner)
        assert ctx.exception.status == 403

        # The JWKS tiers keep their budget.
        charge_partner_by_name("deep_links", self._partner_at_tier(PartnerTier.JWKS))

    def test_failed_repository_probe_keeps_the_charge(self):
        # The repository check is an authenticated GitHub call, so a rejected run has
        # already done outbound work. With a budget of 1, a second attempt must be
        # rate limited rather than probing GitHub again for free.
        self.partner_app.update_provisioning(can_start_wizard_runs=True)
        self.partner_app.update_provisioning_rate_limits(wizard_runs=1)

        with self.settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client"):
            with self.assertRaises(ProvisioningError) as ctx:
                create_wizard_run(
                    partner=self.partner_app,
                    user_id=self.user.id,
                    team=self.team,
                    repository="acme/widgets",
                    branch=None,
                )
            assert ctx.exception.code == "github_integration_required"

            with self.assertRaises(ProvisioningError) as ctx:
                create_wizard_run(
                    partner=self.partner_app,
                    user_id=self.user.id,
                    team=self.team,
                    repository="acme/other",
                    branch=None,
                )
            assert ctx.exception.code == "rate_limited"
