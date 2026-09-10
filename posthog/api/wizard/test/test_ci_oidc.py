import os
import hmac
import json
import time
import uuid
import base64
import hashlib
import importlib
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

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
from posthog.llm.wizard_gateway_token import WIZARD_GATEWAY_CONFIG_REJECTS

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

IDENTITY = {
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "workflow_path": WORKFLOW_PATH,
    "subject": SUBJECT,
}
# A second pinned workflow, so matching runs against a list rather than one entry.
WORKBENCH = {
    "repository": "PostHog/wizard-workbench",
    "repository_id": "1107199518",
    "workflow_path": "PostHog/wizard-workbench/.github/workflows/wizard-ci.yml",
    "subject": "repo:PostHog/wizard-workbench:ref:refs/heads/main",
}

CI_SETTINGS = {
    "WIZARD_CI_OIDC_AUDIENCE": AUDIENCE,
    "WIZARD_CI_REPOSITORY_OWNER_ID": OWNER_ID,
    "WIZARD_CI_IDENTITIES": [IDENTITY, WORKBENCH],
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


def _claims_for(identity: dict) -> dict:
    return {
        "repository": identity["repository"],
        "repository_id": identity["repository_id"],
        "workflow_ref": f"{identity['workflow_path']}@refs/heads/main",
        "sub": identity["subject"],
    }


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
        # The bypass this pin exists for: both claims move to the attacker's ref.
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

    def test_another_pinned_workflow_verifies(self):
        assert verify_github_oidc(token(**_claims_for(WORKBENCH))).repository == WORKBENCH["repository"]

    @pytest.mark.parametrize("field", ["repository", "repository_id", "workflow_path", "subject"])
    def test_one_claim_taken_from_another_pinned_workflow_is_refused(self, field):
        # Every claim matches some entry, but not the same one.
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(**_claims_for({**WORKBENCH, field: IDENTITY[field]})))

    def test_a_workflow_file_named_after_the_pinned_one_plus_an_at_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(workflow_ref=f"{WORKFLOW_PATH}@x.yml@refs/heads/main"))

    def test_an_entry_carries_its_limits_into_the_claims(self):
        limits = {"mints_per_hour": 5, "mints_per_day": 9, "program_ids": ["warehouse-source"], "cap_usd": "20"}
        with override_settings(WIZARD_CI_IDENTITIES=[IDENTITY, {**WORKBENCH, **limits}]):
            workbench = verify_github_oidc(token(**_claims_for(WORKBENCH)))
            wizard = verify_github_oidc(token())
        carried = (workbench.mints_per_hour, workbench.mints_per_day, workbench.program_ids, workbench.cap_usd)
        assert carried == (5, 9, ("warehouse-source",), Decimal("20"))
        assert (wizard.mints_per_hour, wizard.mints_per_day, wizard.program_ids, wizard.cap_usd) == (None,) * 4

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
        # Both clocks move, or the fetch interval serves the cached set before any refetch.
        with patch("posthog.api.wizard.ci_oidc._JWKS_TTL_SECONDS", -1):
            with patch("posthog.api.wizard.ci_oidc._JWKS_MIN_FETCH_INTERVAL_SECONDS", -1):
                claims = verify_github_oidc(token())
        assert _fetch.call_count == 2
        assert claims.repository == REPOSITORY

    def test_an_unrecognized_key_is_refused_rather_than_unresolvable(self, _fetch):
        with pytest.raises(WizardCiOidcError) as refused:
            verify_github_oidc(token(kid="made-up"))
        assert not isinstance(refused.value, WizardCiOidcUnavailable)

    def test_a_caller_arriving_mid_fetch_serves_the_cached_set_instead_of_waiting(self, _fetch):
        # Pins the non-blocking acquire.
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

    def test_an_unreachable_cache_is_unavailable_rather_than_a_replay(self):
        claims = verify_github_oidc(token())
        with patch("posthog.api.wizard.ci_oidc.cache.add", side_effect=Exception("redis down")):
            with pytest.raises(WizardCiOidcUnavailable):
                consume_token_id(claims)

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
        # Same kid, wrong use: GitHub never offered this key for signatures.
        _fetch.return_value = key_set(_jwk(use="enc"))
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token())

    def test_an_expired_token_is_refused(self):
        past = datetime.now(tz=UTC) - timedelta(minutes=30)
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(exp=int(past.timestamp()), iat=int(past.timestamp())))

    @pytest.mark.parametrize("claim", ["exp", "iat", "aud", "sub", "jti"])
    def test_a_missing_required_claim_is_refused(self, claim):
        overrides: dict[str, Any] = {claim: None}
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(token(**overrides))

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

    @pytest.mark.parametrize(
        "missing",
        [{"WIZARD_CI_OIDC_AUDIENCE": ""}, {"WIZARD_CI_REPOSITORY_OWNER_ID": ""}, {"WIZARD_CI_IDENTITIES": []}],
    )
    def test_one_missing_pin_refuses(self, missing):
        with override_settings(**{**CI_SETTINGS, **missing}):
            assert not wizard_ci_oidc_configured()
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token())

    @pytest.mark.parametrize("field", ["repository", "repository_id", "workflow_path", "subject"])
    @pytest.mark.parametrize("value", ["", None, 938775588, ["refs/heads/main"], {"id": 1}])
    def test_an_incomplete_entry_refuses_every_workflow(self, field, value):
        # The token matches the complete entry and is still refused.
        broken = {**WORKBENCH, field: value}
        if value is None:
            del broken[field]
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [IDENTITY, broken]}):
            assert not wizard_ci_oidc_configured()
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token())

    @pytest.mark.parametrize("identities", [None, 0, True, "[]", IDENTITY, [[REPOSITORY]], [None], [5]])
    def test_a_malformed_list_refuses(self, identities):
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": identities}):
            assert not wizard_ci_oidc_configured()

    @pytest.mark.parametrize(
        "extra",
        [
            {"mints_per_hour": 0},
            {"mints_per_hour": "5"},
            {"mints_per_hour": True},
            {"program_ids": []},
            {"program_ids": "posthog-integration"},
            {"program_ids": [""]},
            {"program_ids": [5]},
            {"mints_per_day": 0},
            {"mints_per_day": "5"},
            {"mints_per_day": True},
            {"cap_usd": "0"},
            {"cap_usd": "30.01"},
            {"cap_usd": True},
            {"cap_usd": ["20"]},
            {"mint_per_hour": 5},
        ],
    )
    def test_a_malformed_limit_or_unknown_key_refuses_every_workflow(self, extra):
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [IDENTITY, {**WORKBENCH, **extra}]}):
            assert not wizard_ci_oidc_configured()
            with pytest.raises(WizardCiOidcError):
                verify_github_oidc(token())

    @pytest.mark.parametrize("count", ["mints_per_hour", "mints_per_day"])
    def test_entries_for_one_repository_must_agree_on_their_counts(self, count):
        # Another workflow file too, so only the repository is shared.
        release = {
            **IDENTITY,
            "workflow_path": "PostHog/wizard/.github/workflows/release.yml",
            "subject": "repo:PostHog/wizard:ref:refs/heads/release",
        }
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [IDENTITY, {**release, count: 5}]}):
            assert not wizard_ci_oidc_configured()
        with override_settings(
            **{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [{**IDENTITY, count: 5}, {**release, count: 5}]}
        ):
            assert wizard_ci_oidc_configured()

    def test_a_duplicate_entry_refuses_every_workflow(self):
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [IDENTITY, WORKBENCH, dict(IDENTITY)]}):
            assert not wizard_ci_oidc_configured()

    def test_a_malformed_list_is_counted_and_an_empty_one_is_not(self):
        rejects = WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="ci_identities")
        before = rejects._value.get()
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [{**IDENTITY, "subject": ""}]}):
            wizard_ci_oidc_configured()
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": []}):
            wizard_ci_oidc_configured()
        assert rejects._value.get() == before + 1

    def test_an_identity_list_that_is_not_json_configures_none(self):
        web_settings = importlib.import_module("posthog.settings.web")
        try:
            with patch.dict(os.environ, {"WIZARD_CI_IDENTITIES": "not json"}):
                importlib.reload(web_settings)
                assert (web_settings.WIZARD_CI_IDENTITIES, web_settings.WIZARD_CI_IDENTITIES_INVALID) == ([], True)
        finally:
            importlib.reload(web_settings)
        rejects = WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="ci_identities")
        before = rejects._value.get()
        with override_settings(**{**CI_SETTINGS, "WIZARD_CI_IDENTITIES": [], "WIZARD_CI_IDENTITIES_INVALID": True}):
            assert not wizard_ci_oidc_configured()
        assert rejects._value.get() == before + 1

    def test_the_ci_mint_limits_default_when_unset(self):
        web_settings = importlib.import_module("posthog.settings.web")
        unset = {
            k: v for k, v in os.environ.items() if k not in ("WIZARD_CI_MINTS_PER_HOUR", "WIZARD_CI_MINTS_PER_DAY")
        }
        try:
            with patch.dict(os.environ, unset, clear=True):
                importlib.reload(web_settings)
                assert (web_settings.WIZARD_CI_MINTS_PER_HOUR, web_settings.WIZARD_CI_MINTS_PER_DAY) == (20, 100)
        finally:
            importlib.reload(web_settings)


class TestLooksLikeJwt:
    @pytest.mark.parametrize("token", ["a.b.c", "eyJhbGci.eyJzdWIi.sig"])
    def test_a_three_part_token_routes_here(self, token):
        assert looks_like_jwt(token)

    @pytest.mark.parametrize("token", ["pha_abc", "phx_abc", "phs_abc", "abc", "a.b", "a.b.c.d"])
    def test_a_posthog_credential_does_not(self, token):
        assert not looks_like_jwt(token)
