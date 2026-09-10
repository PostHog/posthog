import hmac
import json
import uuid
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.api.wizard.ci_oidc import (
    GITHUB_OIDC_ISSUER,
    WizardCiOidcError,
    WizardCiOidcUnavailable,
    looks_like_jwt,
    reset_key_set_cache,
    verify_github_oidc,
    wizard_ci_oidc_configured,
)

# One key for the module: generation dominates these tests.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

AUDIENCE = "posthog-wizard-ci"
REPOSITORY = "PostHog/wizard"
REPOSITORY_ID = "938775588"
OWNER_ID = "60330232"
WORKFLOW_PATH = "PostHog/wizard/.github/workflows/smoke-test.yml"
SUBJECT = "repo:PostHog/wizard:ref:refs/heads/main"
KID = "github-signing-key-1"

CI_SETTINGS = {
    "WIZARD_CI_OIDC_AUDIENCE": AUDIENCE,
    "WIZARD_CI_REPOSITORY": REPOSITORY,
    "WIZARD_CI_REPOSITORY_ID": REPOSITORY_ID,
    "WIZARD_CI_REPOSITORY_OWNER_ID": OWNER_ID,
    "WIZARD_CI_WORKFLOW_PATH": WORKFLOW_PATH,
    "WIZARD_CI_SUBJECT": SUBJECT,
}


def _jwk(kid: str = KID, use: str = "sig") -> dict:
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PUBLIC_KEY))
    key.update({"kid": kid, "use": use, "alg": "RS256"})
    return key


def key_set(*keys: dict) -> jwt.PyJWKSet:
    """Also imported by test_ci_mint for its unstubbed end-to-end cases."""
    return jwt.PyJWKSet.from_dict({"keys": list(keys) or [_jwk()]})


def token(kid: str = KID, **overrides) -> str:
    """A token GitHub would issue for the smoke-test workflow, before overrides."""
    now = datetime.now(tz=UTC)
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "jti": str(uuid.uuid4()),
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "repository_owner_id": OWNER_ID,
        "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
        "run_id": "42",
    }
    claims.update(overrides)
    for key in [k for k, v in claims.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def _fetch():
    reset_key_set_cache()
    cache.clear()
    with patch("posthog.api.wizard.ci_oidc._fetch_key_set", return_value=key_set()) as fetch:
        yield fetch
    reset_key_set_cache()
    cache.clear()


class TestVerifyGitHubOidc:
    @pytest.fixture(autouse=True)
    def _ci_settings(self):
        with override_settings(**CI_SETTINGS):
            yield

    def test_a_smoke_test_token_verifies(self):
        claims = verify_github_oidc(token())
        assert claims.repository == REPOSITORY
        assert claims.repository_owner_id == OWNER_ID
        assert claims.run_id == "42"

    def test_another_audience_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(aud="sts.amazonaws.com"))

    def test_another_issuer_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(iss="https://evil.example.com"))

    def test_another_repository_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(repository="PostHog/not-the-wizard"))

    def test_another_owner_id_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(repository_owner_id="999"))

    def test_a_matching_name_under_another_owner_id_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(repository_owner_id="999", repository=REPOSITORY))

    def test_another_workflow_in_the_same_repository_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(workflow_ref="PostHog/wizard/.github/workflows/publish.yml@refs/heads/main"))

    def test_the_same_workflow_on_another_ref_is_refused(self):
        # The bypass this pin exists for: both claims move to the attacker's ref
        # together.
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                token(
                    sub=f"repo:{REPOSITORY}:ref:refs/heads/attacker",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/heads/attacker",
                )
            )

    def test_a_ref_that_extends_the_pinned_ref_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                token(
                    sub=f"repo:{REPOSITORY}:ref:refs/heads/main-x",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/heads/main-x",
                )
            )

    def test_a_pull_request_run_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                token(
                    sub=f"repo:{REPOSITORY}:pull_request",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/pull/1/merge",
                )
            )

    def test_a_workflow_path_that_extends_the_pinned_one_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(workflow_ref=f"{WORKFLOW_PATH}.bak@refs/heads/main"))

    def test_a_token_for_another_issuer_costs_no_fetch(self, _fetch):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(iss="https://evil.example.com"))
        _fetch.assert_not_called()

    def test_a_token_for_another_audience_costs_no_fetch(self, _fetch):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(aud="sts.amazonaws.com"))
        _fetch.assert_not_called()

    def test_a_smoke_test_token_still_reaches_the_fetch(self, _fetch):
        # Derived from the two above: the pre-filter must not become the check.
        verify_github_oidc(token())
        _fetch.assert_called_once()

    def test_a_second_verification_reuses_the_cached_key_set(self, _fetch):
        verify_github_oidc(token())
        verify_github_oidc(token())
        _fetch.assert_called_once()

    def test_an_unknown_kid_refetches_once_then_stops(self, _fetch):
        # The amplification this bounds: PyJWKClient refetches on every miss, so
        # without the interval each invented token would reach GitHub.
        for _ in range(5):
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token(kid="made-up"))
        assert _fetch.call_count == 1

    def test_a_failing_fetch_is_not_retried_until_the_interval_passes(self, _fetch):
        # A failed attempt has to spend the interval too. Otherwise an unreachable
        # GitHub puts one outbound request behind every request that arrives.
        _fetch.side_effect = Exception("github unreachable")
        for _ in range(5):
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token())
        assert _fetch.call_count == 1

    def test_a_token_is_unresolvable_rather_than_invalid_when_no_key_set_exists(self, _fetch):
        # The caller retries an outage; it does not retry a bad token.
        _fetch.side_effect = Exception("github unreachable")
        with pytest.raises(WizardCiOidcUnavailable):
            verify_github_oidc(token())

    def test_a_failed_refetch_keeps_serving_the_cached_key_set(self, _fetch):
        verify_github_oidc(token())
        _fetch.side_effect = Exception("github unreachable")
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            claims = verify_github_oidc(token())
        assert claims.repository == REPOSITORY

    def test_an_unrecognized_key_is_refused_rather_than_unresolvable(self, _fetch):
        # A key set we hold and a kid that is not in it is the caller's problem.
        with pytest.raises(WizardCiOidcError) as refused:
            verify_github_oidc(token(kid="made-up"))
        assert not isinstance(refused.value, WizardCiOidcUnavailable)

    def test_an_expired_key_set_is_refetched(self, _fetch):
        verify_github_oidc(token())
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                verify_github_oidc(token())
        assert _fetch.call_count == 2

    def test_a_replayed_token_is_refused(self):
        bearer = token()
        verify_github_oidc(bearer)
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(bearer)

    def test_a_second_distinct_token_still_verifies(self):
        # Derived from the replay test: the cache must key on jti, not on the run.
        verify_github_oidc(token())
        assert verify_github_oidc(token()).repository == REPOSITORY

    def test_a_replay_still_verifies_when_the_cache_is_unreachable(self):
        # Refusing every CI run because Redis blinked is the worse trade; the mint
        # limits still bound a replay.
        bearer = token()
        with patch("posthog.api.wizard.ci_oidc.cache.add", side_effect=Exception("redis down")):
            assert verify_github_oidc(bearer).repository == REPOSITORY
            assert verify_github_oidc(bearer).repository == REPOSITORY

    def test_another_repository_id_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(repository_id="1"))

    def test_a_renamed_repository_reusing_the_name_is_refused(self):
        # The name pins pass; only the immutable id catches this.
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(repository_id="999999"))

    def test_a_token_with_no_kid_is_refused_without_a_fetch(self, _fetch):
        now = datetime.now(tz=UTC)
        unkeyed = jwt.encode(
            {
                "iss": GITHUB_OIDC_ISSUER,
                "aud": AUDIENCE,
                "sub": SUBJECT,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=10)).timestamp()),
                "jti": str(uuid.uuid4()),
            },
            _PRIVATE_KEY,
            algorithm="RS256",
        )
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(unkeyed)
        _fetch.assert_not_called()

    def test_an_encryption_key_is_not_used_to_verify(self, _fetch):
        # Same kid, wrong use: verifying with it would accept a key GitHub never
        # offered for signatures.
        _fetch.return_value = key_set(_jwk(use="enc"))
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token())

    def test_an_expired_token_is_refused(self):
        past = datetime.now(tz=UTC) - timedelta(minutes=30)
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(exp=int(past.timestamp()), iat=int(past.timestamp())))

    @pytest.mark.parametrize("claim", ["exp", "iat", "aud", "sub", "jti"])
    def test_a_missing_required_claim_is_refused(self, claim):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(**{claim: None}))

    def test_a_token_signed_with_another_key_is_refused(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(tz=UTC)
        forged = jwt.encode(
            {
                "iss": GITHUB_OIDC_ISSUER,
                "aud": AUDIENCE,
                "sub": SUBJECT,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=10)).timestamp()),
                "jti": str(uuid.uuid4()),
                "repository": REPOSITORY,
                "repository_id": REPOSITORY_ID,
                "repository_owner_id": OWNER_ID,
                "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
            },
            other,
            algorithm="RS256",
            headers={"kid": KID},
        )
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(forged)

    def test_a_symmetric_algorithm_is_refused(self):
        # Assembled by hand: PyJWT will not encode a PEM as an HMAC secret.
        public_pem = _PUBLIC_KEY.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        now = datetime.now(tz=UTC)
        claims = {
            "iss": GITHUB_OIDC_ISSUER,
            "aud": AUDIENCE,
            "sub": SUBJECT,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "jti": str(uuid.uuid4()),
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "repository_owner_id": OWNER_ID,
            "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
        }

        def segment(payload: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

        header = {"alg": "HS256", "typ": "JWT", "kid": KID}
        signing_input = f"{segment(header)}.{segment(claims)}"
        signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
        forged = f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(forged)

    def test_an_unreachable_key_set_refuses(self, _fetch):
        _fetch.side_effect = Exception("jwks unreachable")
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token())

    def test_a_malformed_token_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc("not-a-jwt")


class TestConfiguration:
    @override_settings(**CI_SETTINGS)
    def test_every_pin_set_is_configured(self):
        assert wizard_ci_oidc_configured()

    @pytest.mark.parametrize("missing", list(CI_SETTINGS))
    def test_one_missing_pin_refuses(self, missing):
        with override_settings(**{**CI_SETTINGS, missing: ""}):
            assert not wizard_ci_oidc_configured()
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token())


class TestLooksLikeJwt:
    @pytest.mark.parametrize("token", ["a.b.c", "eyJhbGci.eyJzdWIi.sig"])
    def test_a_three_part_token_routes_here(self, token):
        assert looks_like_jwt(token)

    @pytest.mark.parametrize("token", ["pha_abc", "phx_abc", "phs_abc", "abc", "a.b", "a.b.c.d"])
    def test_a_posthog_credential_does_not(self, token):
        assert not looks_like_jwt(token)
