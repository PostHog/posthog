import hmac
import json
import time
import uuid
import base64
import hashlib
import threading
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
    consume_token_id,
    looks_like_jwt,
    release_token_id,
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
        # Without the interval, every invented kid would reach GitHub.
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
        # Both clocks have to move, or the interval returns the cached set before
        # the refetch this test is named for is ever attempted.
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                claims = verify_github_oidc(token())
        assert _fetch.call_count == 2
        assert claims.repository == REPOSITORY

    def test_an_unrecognized_key_is_refused_rather_than_unresolvable(self, _fetch):
        # A key set we hold and a kid that is not in it is the caller's problem.
        with pytest.raises(WizardCiOidcError) as refused:
            verify_github_oidc(token(kid="made-up"))
        assert not isinstance(refused.value, WizardCiOidcUnavailable)

    def test_a_caller_arriving_mid_fetch_serves_the_cached_set_instead_of_waiting(self, _fetch):
        # Pins the non-blocking acquire. Taking the lock normally would park every
        # arriving worker thread on a fetch that runs for up to ten seconds.
        verify_github_oidc(token())
        started, release = threading.Event(), threading.Event()

        def slow_fetch():
            started.set()
            release.wait(10)
            return key_set()

        _fetch.side_effect = slow_fetch
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                fetcher = threading.Thread(target=lambda: verify_github_oidc(token()), daemon=True)
                fetcher.start()
                try:
                    assert started.wait(5)
                    began = time.monotonic()
                    verify_github_oidc(token())
                    waited = time.monotonic() - began
                finally:
                    release.set()
                    fetcher.join(10)
        assert waited < 2

    def test_a_key_set_past_the_staleness_ceiling_stops_serving(self, _fetch):
        # Otherwise an unreachable GitHub means a key it revoked verifies forever.
        verify_github_oidc(token())
        _fetch.side_effect = Exception("github unreachable")
        with patch("posthog.api.wizard.ci_oidc._JWKS_MAX_STALE_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                with pytest.raises(WizardCiOidcUnavailable):
                    verify_github_oidc(token())
        assert _fetch.call_count == 2

    def test_an_expired_key_set_is_refetched(self, _fetch):
        verify_github_oidc(token())
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                verify_github_oidc(token())
        assert _fetch.call_count == 2

    def test_verification_leaves_the_single_use_unspent(self):
        # The mint spends it, so a refused mint can hand it back and let the same
        # run retry with the token it already has.
        bearer = token()
        assert verify_github_oidc(bearer).repository == REPOSITORY
        assert verify_github_oidc(bearer).repository == REPOSITORY

    def test_a_token_id_is_consumed_once(self):
        claims = verify_github_oidc(token())
        assert consume_token_id(claims)
        assert not consume_token_id(claims)

    def test_a_released_token_id_can_be_consumed_again(self):
        claims = verify_github_oidc(token())
        assert consume_token_id(claims)
        release_token_id(claims)
        assert consume_token_id(claims)

    def test_a_token_valid_for_longer_than_we_track_is_refused(self):
        # The replay marker would have to be held for as long.
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(exp=int(time.time()) + 10**9))

    def test_the_replay_marker_outlives_the_token(self):
        # A marker that expires first leaves the rest of the token's life open.
        claims = verify_github_oidc(token(exp=int(time.time()) + 900))
        with patch("posthog.api.wizard.ci_oidc.cache.add", return_value=True) as add:
            consume_token_id(claims)
        held = add.call_args[0][2]
        assert held >= claims.expires_at - int(time.time())
        assert held <= 3600 + 60

    def test_an_unreachable_cache_refuses_the_single_use(self):
        # The hourly mint limit lives in this same cache, so failing open here
        # would leave a captured token bounded by nothing.
        claims = verify_github_oidc(token())
        with patch("posthog.api.wizard.ci_oidc.cache.add", side_effect=Exception("redis down")):
            assert not consume_token_id(claims)

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
