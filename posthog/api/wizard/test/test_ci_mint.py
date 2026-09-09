from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

from posthog.api.wizard.ci_oidc import GitHubOidcClaims, WizardCiOidcError

MINTED = {"token": "phe_ci_token", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "2.000000"}

CLAIMS = GitHubOidcClaims(
    repository="PostHog/wizard",
    repository_owner_id="11801436",
    workflow_ref="PostHog/wizard/.github/workflows/smoke-test.yml@refs/heads/main",
    run_id="42",
)

# These cases patch the verifier, so they exercise the endpoint.
CI_BEARER = "header.payload.signature"


class WizardCiMintTests(APIBaseTest):
    GATEWAY_TOKEN_URL = "/api/wizard/gateway_token"

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
            "WIZARD_CI_REPOSITORY_OWNER_ID": "11801436",
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
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=CLAIMS):
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
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=CLAIMS):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_program_unknown"
        mint.assert_not_called()

    def test_a_program_with_no_product_node_is_refused(self):
        with self._settings(WIZARD_GATEWAY_PROGRAM_IDS=["other"], WIZARD_CI_PROGRAM_IDS=["integration"]):
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=CLAIMS):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_program_unknown"
        mint.assert_not_called()

    def test_an_unset_ci_team_refuses(self):
        with self._settings(WIZARD_CI_TEAM_ID=0):
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=CLAIMS):
                with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED) as mint:
                    response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._code(response) == "ci_unconfigured"
        mint.assert_not_called()

    def test_the_hourly_limit_bounds_a_retry_loop(self):
        with self._settings(WIZARD_CI_MINTS_PER_HOUR=2):
            with patch("posthog.api.wizard.http.verify_github_oidc", return_value=CLAIMS):
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

    def test_a_forwarded_header_cannot_buy_a_fresh_bucket(self):
        # Unvouched, the header is caller-written: rotating it would buy quota.
        with self._settings(WIZARD_CI_VERIFY_PER_MINUTE=1):
            with patch(
                "posthog.api.wizard.http.verify_github_oidc",
                side_effect=WizardCiOidcError("token failed verification"),
            ):
                first = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.1")
                second = self._post(REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="203.0.113.2")

        assert first.status_code == status.HTTP_401_UNAUTHORIZED
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
