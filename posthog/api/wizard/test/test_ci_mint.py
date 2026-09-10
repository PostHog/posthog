import time
import uuid
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

import posthog.api.wizard.test.test_ci_oidc as oidc
from posthog.api.wizard.ci_oidc import GitHubOidcClaims, WizardCiOidcError, WizardCiOidcUnavailable, reset_key_set_cache
from posthog.llm.wizard_gateway_token import WizardGatewayMintError

MINTED = {"token": "phe_ci_token", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "2.000000"}


def _claims(**overrides) -> GitHubOidcClaims:
    """A fresh identity per call: each CI run presents its own single-use token."""
    fields = {
        "repository": "PostHog/wizard",
        "repository_id": "938775588",
        "repository_owner_id": "60330232",
        "workflow_ref": "PostHog/wizard/.github/workflows/smoke-test.yml@refs/heads/main",
        "run_id": "42",
        "token_id": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 600,
    }
    fields.update(overrides)
    return GitHubOidcClaims(**fields)


def _verified(*_args, **_kwargs) -> GitHubOidcClaims:
    return _claims()


CI_BEARER = "header.payload.signature"


class WizardCiMintTests(APIBaseTest):
    GATEWAY_TOKEN_URL = "/api/wizard/gateway_token"

    def setUp(self):
        super().setUp()
        rollout = patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
        rollout.start()
        self.addCleanup(rollout.stop)

    def tearDown(self):
        super().tearDown()
        cache.clear()

    def _settings(self, **extra):
        base = {
            "WIZARD_GATEWAY_URL": "https://ai-gateway.us.posthog.com",
            "WIZARD_GATEWAY_MINT_KEY": "phs_wizard_secret",
            "WIZARD_GATEWAY_CLIENT_IDS": ["wizard-client-id"],
            "WIZARD_GATEWAY_PROGRAM_IDS": ["integration"],
            "WIZARD_CI_OIDC_AUDIENCE": "posthog-wizard-ci",
            "WIZARD_CI_REPOSITORY": "PostHog/wizard",
            "WIZARD_CI_REPOSITORY_ID": "938775588",
            "WIZARD_CI_REPOSITORY_OWNER_ID": "60330232",
            "WIZARD_CI_WORKFLOW_PATH": "PostHog/wizard/.github/workflows/smoke-test.yml",
            "WIZARD_CI_SUBJECT": "repo:PostHog/wizard:ref:refs/heads/main",
            "WIZARD_CI_VERIFY_PER_MINUTE": 30,
            "WIZARD_CI_TEAM_ID": self.team.id,
            "WIZARD_CI_PROGRAM_IDS": ["integration"],
            "WIZARD_CI_CAP_USD": "2",
            "WIZARD_CI_TTL_SECONDS": 3600,
            "WIZARD_CI_MINTS_PER_HOUR": 20,
        }
        base.update(extra)
        return override_settings(**base)

    def _post(self, program="integration", bearer=CI_BEARER, **extra):
        return self.client.post(
            self.GATEWAY_TOKEN_URL,
            {"program": program, "reads_refusal_reason": True},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {bearer}",
            **extra,
        )

    def _code(self, response):
        detail = response.json().get("code")
        return detail

    def test_a_verified_run_mints_a_capped_pinned_token(self):
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["token"] == "phe_ci_token"
        kwargs = mint.call_args.kwargs
        assert kwargs["product"] == "wizard:integration"
        assert kwargs["cap_usd"] == Decimal("2.000000")
        assert kwargs["ttl_seconds"] == 3600
        assert kwargs["obo"] == str(self.team.organization_id)
        assert kwargs["user"] == "wizard-ci:PostHog/wizard"

    def test_an_unverified_token_is_refused(self):
        with self._settings():
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token was issued to another repository"),
            ):
                response = self._post()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert self._code(response) == "ci_invalid_token"

    def test_a_program_outside_the_ci_list_is_refused(self):
        # Has a product node; without the CI list it would mint.
        with self._settings(WIZARD_CI_PROGRAM_IDS=["something-else"]):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_program_unknown"
        mint.assert_not_called()

    def test_a_program_with_no_product_node_is_refused(self):
        with self._settings(WIZARD_GATEWAY_PROGRAM_IDS=["other"], WIZARD_CI_PROGRAM_IDS=["integration"]):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_program_unknown"
        mint.assert_not_called()

    def test_an_unset_ci_team_refuses(self):
        with self._settings(WIZARD_CI_TEAM_ID=0):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_unconfigured"
        mint.assert_not_called()

    def test_the_hourly_limit_bounds_a_retry_loop(self):
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=2):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                    assert self._post().status_code == status.HTTP_201_CREATED
                    assert self._post().status_code == status.HTTP_201_CREATED
                    third = self._post()

        assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert self._code(third) == "ci_throttled"

    def test_an_unconfigured_instance_leaves_the_oauth_chain_alone(self):
        with self._settings(WIZARD_CI_OIDC_AUDIENCE=""):
            with patch("posthog.api.wizard.http.verify_github_oidc") as verify:
                response = self._post()

        verify.assert_not_called()
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert self._code(response) == "invalid_token"

    def test_a_posthog_credential_never_routes_to_the_ci_path(self):
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc") as verify:
                response = self._post(bearer="pha_not_a_jwt")

        verify.assert_not_called()
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert self._code(response) == "invalid_token"

    def test_verification_is_throttled_before_the_key_fetch(self):
        with self._settings(WIZARD_CI_VERIFY_PER_MINUTE=2):
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token failed verification"),
            ) as verify:
                assert self._post().status_code == status.HTTP_401_UNAUTHORIZED
                assert self._post().status_code == status.HTTP_401_UNAUTHORIZED
                third = self._post()

        assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert self._code(third) == "ci_verify_throttled"
        # The refused third request must not have reached verification at all.
        assert verify.call_count == 2

    def test_the_verify_bucket_is_per_address(self):
        # Pins the key itself: a constant key would 429 the second caller too.
        with self._settings(WIZARD_CI_VERIFY_PER_MINUTE=1):
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token failed verification"),
            ):
                assert self._post(REMOTE_ADDR="10.0.0.1").status_code == status.HTTP_401_UNAUTHORIZED
                repeat = self._post(REMOTE_ADDR="10.0.0.1")
                other = self._post(REMOTE_ADDR="10.0.0.2")

        assert repeat.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert other.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_forwarded_header_cannot_buy_a_fresh_bucket_when_no_proxy_is_trusted(self):
        with self._settings(WIZARD_CI_VERIFY_PER_MINUTE=1, TRUST_ALL_PROXIES=False, TRUSTED_PROXIES=None):
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token failed verification"),
            ):
                first = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.1")
                second = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.2")

        assert first.status_code == status.HTTP_401_UNAUTHORIZED
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_a_forwarded_header_does_buy_a_fresh_bucket_on_cloud(self):
        # Cloud sets TRUST_ALL_PROXIES, so this throttle reads a caller-written
        # address. Pinned so nobody reads the limit as the protection.
        with self._settings(WIZARD_CI_VERIFY_PER_MINUTE=1, TRUST_ALL_PROXIES=True, USE_X_FORWARDED_HOST=True):
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token failed verification"),
            ):
                first = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.1")
                second = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.2")

        assert first.status_code == status.HTTP_401_UNAUTHORIZED
        assert second.status_code == status.HTTP_401_UNAUTHORIZED

    def test_the_same_token_cannot_mint_twice(self):
        fixed = _claims()
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=fixed):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                    first = self._post()
                    second = self._post()

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_401_UNAUTHORIZED
        assert self._code(second) == "ci_token_replayed"

    def test_a_refunded_mint_failure_lets_the_same_token_retry(self):
        # The slot and the single use are handed back together, or the retry the
        # refund exists for would be refused as a replay.
        fixed = _claims()
        with self._settings():
            with patch("posthog.api.wizard.http.release_token_id") as release:
                with patch("posthog.api.wizard.http.verify_github_oidc", return_value=fixed):
                    with patch(
                        "posthog.api.wizard.http.mint_wizard_gateway_token",
                        side_effect=WizardGatewayMintError("gateway down", token_may_exist=False),
                    ):
                        assert self._post().status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            release.assert_called_once()

        cache.clear()
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=fixed):
                with patch(
                    "posthog.api.wizard.http.mint_wizard_gateway_token",
                    side_effect=WizardGatewayMintError("gateway down", token_may_exist=False),
                ):
                    failed = self._post()
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                    retried = self._post()

        assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert retried.status_code == status.HTTP_201_CREATED

    def test_an_unreachable_cache_refuses_rather_than_minting_unbounded(self):
        # The hourly limit and the replay guard share this cache, so failing open
        # would leave one captured token bounded by nothing.
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.rate_limit.cache.add", side_effect=Exception("redis down")):
                    with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                        response = self._post()

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert self._code(response) == "ci_throttled"
        mint.assert_not_called()

    def test_a_replay_hands_back_the_slot_it_charged(self):
        # Otherwise one captured token burns the hour and refuses the runs it was
        # captured from.
        fixed = _claims()
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=2):
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=fixed):
                with patch("posthog.api.wizard.http.refund_wizard_mint") as refund:
                    with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                        assert self._post().status_code == status.HTTP_201_CREATED
                        replayed = self._post()

        assert replayed.status_code == status.HTTP_401_UNAUTHORIZED
        refund.assert_called_once()

    def test_a_failure_that_may_have_issued_a_token_keeps_the_single_use(self):
        # The token may be live, so the use it spent must stay spent.
        fixed = _claims()
        with self._settings():
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=fixed):
                with patch("posthog.api.wizard.http.release_token_id") as release:
                    with patch(
                        "posthog.api.wizard.http.mint_wizard_gateway_token",
                        side_effect=WizardGatewayMintError("timed out", token_may_exist=True),
                    ):
                        assert self._post().status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            release.assert_not_called()

    def test_an_unreachable_key_set_is_not_reported_as_a_bad_token(self):
        with self._settings():
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcUnavailable("no GitHub signing key is available right now"),
            ):
                response = self._post()

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert self._code(response) == "ci_verify_unavailable"

    def test_the_kill_switch_refuses_a_verified_run(self):
        with self._settings():
            with patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=False):
                with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                    with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                        response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_not_rolled_out"
        mint.assert_not_called()

    def test_a_flag_outage_still_mints(self):
        # Only a literal False refuses; the legacy path is gone, so reading an
        # outage as "switched off" would be a global CI outage.
        with self._settings():
            with patch(
                "posthog.api.wizard.http.posthoganalytics.feature_enabled",
                side_effect=Exception("flag service down"),
            ):
                with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                    with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                        response = self._post()

        assert response.status_code == status.HTTP_201_CREATED

    def test_a_configured_team_that_does_not_exist_is_refused(self):
        with self._settings(WIZARD_CI_TEAM_ID=99_999_999):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_team_missing"
        mint.assert_not_called()

    def test_a_mint_failure_returns_its_hourly_slot(self):
        # Asserted on the refund itself: the hourly counter buckets on the wall
        # clock, so a rollover could let a retry succeed with the refund deleted.
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=1):
            with patch("posthog.api.wizard.http.refund_wizard_mint") as refund:
                with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                    with patch(
                        "posthog.api.wizard.http.mint_wizard_gateway_token",
                        side_effect=WizardGatewayMintError("gateway down", token_may_exist=False),
                    ):
                        assert self._post().status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            refund.assert_called_once()

        cache.clear()
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=1):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch(
                    "posthog.api.wizard.http.mint_wizard_gateway_token",
                    side_effect=WizardGatewayMintError("gateway down", token_may_exist=False),
                ):
                    failed = self._post()
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                    retried = self._post()

        assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert retried.status_code == status.HTTP_201_CREATED

    def test_a_mint_failure_that_may_have_issued_a_token_keeps_its_slot(self):
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=1):
            with patch("posthog.api.wizard.http.refund_wizard_mint") as refund:
                with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                    with patch(
                        "posthog.api.wizard.http.mint_wizard_gateway_token",
                        side_effect=WizardGatewayMintError("timed out", token_may_exist=True),
                    ):
                        assert self._post().status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            refund.assert_not_called()

        cache.clear()
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=1):
            with patch("posthog.api.wizard.http.verify_github_oidc", side_effect=_verified):
                with patch(
                    "posthog.api.wizard.http.mint_wizard_gateway_token",
                    side_effect=WizardGatewayMintError("timed out", token_may_exist=True),
                ):
                    failed = self._post()
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                    retried = self._post()

        assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert retried.status_code == status.HTTP_429_TOO_MANY_REQUESTS


class WizardCiMintEndToEndTests(APIBaseTest):
    """Nothing stubs the verifier here, so the bearer really is verified.

    The cases above patch `verify_github_oidc` to reach the gates behind it, which
    leaves the wiring from Authorization header to pinned claims unexercised.
    """

    GATEWAY_TOKEN_URL = "/api/wizard/gateway_token"

    def setUp(self):
        super().setUp()
        reset_key_set_cache()
        keys = patch("posthog.api.wizard.ci_oidc._fetch_key_set", return_value=oidc.key_set())
        keys.start()
        self.addCleanup(keys.stop)
        rollout = patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
        rollout.start()
        self.addCleanup(rollout.stop)

    def tearDown(self):
        super().tearDown()
        reset_key_set_cache()
        cache.clear()

    def _settings(self, **extra):
        base = {
            "WIZARD_GATEWAY_URL": "https://ai-gateway.us.posthog.com",
            "WIZARD_GATEWAY_MINT_KEY": "phs_wizard_secret",
            "WIZARD_GATEWAY_CLIENT_IDS": ["wizard-client-id"],
            "WIZARD_GATEWAY_PROGRAM_IDS": ["integration"],
            "WIZARD_CI_OIDC_AUDIENCE": oidc.AUDIENCE,
            "WIZARD_CI_REPOSITORY": oidc.REPOSITORY,
            "WIZARD_CI_REPOSITORY_ID": oidc.REPOSITORY_ID,
            "WIZARD_CI_REPOSITORY_OWNER_ID": oidc.OWNER_ID,
            "WIZARD_CI_WORKFLOW_PATH": oidc.WORKFLOW_PATH,
            "WIZARD_CI_SUBJECT": oidc.SUBJECT,
            "WIZARD_CI_VERIFY_PER_MINUTE": 30,
            "WIZARD_CI_TEAM_ID": self.team.id,
            "WIZARD_CI_PROGRAM_IDS": ["integration"],
            "WIZARD_CI_CAP_USD": "2",
            "WIZARD_CI_TTL_SECONDS": 3600,
            "WIZARD_CI_MINTS_PER_HOUR": 20,
        }
        base.update(extra)
        return override_settings(**base)

    def _post(self, bearer):
        return self.client.post(
            self.GATEWAY_TOKEN_URL,
            {"program": "integration", "reads_refusal_reason": True},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {bearer}",
        )

    def test_a_real_signed_token_mints(self):
        with self._settings():
            with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                response = self._post(oidc.token())

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert mint.call_args.kwargs["user"] == f"wizard-ci:{oidc.REPOSITORY}"

    def test_a_real_token_for_another_ref_is_refused(self):
        forged = oidc.token(
            sub=f"repo:{oidc.REPOSITORY}:ref:refs/heads/attacker",
            workflow_ref=f"{oidc.WORKFLOW_PATH}@refs/heads/attacker",
        )
        with self._settings():
            with patch("posthog.api.wizard.http.mint_wizard_gateway_token") as mint:
                response = self._post(forged)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json().get("code") == "ci_invalid_token"
        mint.assert_not_called()

    def test_a_real_token_replayed_is_refused_the_second_time(self):
        bearer = oidc.token()
        with self._settings():
            with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED):
                first = self._post(bearer)
                second = self._post(bearer)

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_401_UNAUTHORIZED
