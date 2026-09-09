import hmac
import json
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.test import override_settings

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.api.wizard.ci_oidc import (
    GITHUB_OIDC_ISSUER,
    WizardCiOidcError,
    looks_like_jwt,
    verify_github_oidc,
    wizard_ci_oidc_configured,
)

# One key for the module: generation dominates these tests.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

AUDIENCE = "posthog-wizard-ci"
REPOSITORY = "PostHog/wizard"
OWNER_ID = "11801436"
WORKFLOW_PATH = "PostHog/wizard/.github/workflows/smoke-test.yml"
SUBJECT = "repo:PostHog/wizard:ref:refs/heads/main"

CI_SETTINGS = {
    "WIZARD_CI_OIDC_AUDIENCE": AUDIENCE,
    "WIZARD_CI_REPOSITORY": REPOSITORY,
    "WIZARD_CI_REPOSITORY_OWNER_ID": OWNER_ID,
    "WIZARD_CI_WORKFLOW_PATH": WORKFLOW_PATH,
    "WIZARD_CI_SUBJECT": SUBJECT,
}


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


def _token(**overrides) -> str:
    """A token GitHub would issue for the smoke-test workflow, before overrides."""
    now = datetime.now(tz=UTC)
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "repository": REPOSITORY,
        "repository_owner_id": OWNER_ID,
        "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
        "run_id": "42",
    }
    claims.update(overrides)
    for key in [k for k, v in claims.items() if v is None]:
        del claims[key]
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _jwks():
    with patch("posthog.api.wizard.ci_oidc._get_jwks_client") as client:
        client.return_value.get_signing_key_from_jwt.return_value = _FakeSigningKey(_PUBLIC_KEY)
        yield client


class TestVerifyGitHubOidc:
    @pytest.fixture(autouse=True)
    def _ci_settings(self):
        with override_settings(**CI_SETTINGS):
            yield

    def test_a_smoke_test_token_verifies(self):
        claims = verify_github_oidc(_token())
        assert claims.repository == REPOSITORY
        assert claims.repository_owner_id == OWNER_ID
        assert claims.run_id == "42"

    def test_another_audience_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(aud="sts.amazonaws.com"))

    def test_another_issuer_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(iss="https://evil.example.com"))

    def test_another_repository_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(repository="PostHog/not-the-wizard"))

    def test_another_owner_id_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(repository_owner_id="999"))

    def test_a_matching_name_under_another_owner_id_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(repository_owner_id="999", repository=REPOSITORY))

    def test_another_workflow_in_the_same_repository_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(workflow_ref="PostHog/wizard/.github/workflows/publish.yml@refs/heads/main"))

    def test_the_same_workflow_on_another_ref_is_refused(self):
        # The bypass this pin exists for: both claims move to the attacker's ref
        # together.
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                _token(
                    sub=f"repo:{REPOSITORY}:ref:refs/heads/attacker",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/heads/attacker",
                )
            )

    def test_a_ref_that_extends_the_pinned_ref_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                _token(
                    sub=f"repo:{REPOSITORY}:ref:refs/heads/main-x",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/heads/main-x",
                )
            )

    def test_a_pull_request_run_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(
                _token(
                    sub=f"repo:{REPOSITORY}:pull_request",
                    workflow_ref=f"{WORKFLOW_PATH}@refs/pull/1/merge",
                )
            )

    def test_a_workflow_path_that_extends_the_pinned_one_is_refused(self):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(workflow_ref=f"{WORKFLOW_PATH}.bak@refs/heads/main"))

    def test_a_token_for_another_issuer_costs_no_key_fetch(self, _jwks):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(iss="https://evil.example.com"))
        _jwks.return_value.get_signing_key_from_jwt.assert_not_called()

    def test_a_token_for_another_audience_costs_no_key_fetch(self, _jwks):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(aud="sts.amazonaws.com"))
        _jwks.return_value.get_signing_key_from_jwt.assert_not_called()

    def test_a_smoke_test_token_still_reaches_the_key_fetch(self, _jwks):
        # Derived from the two above: the pre-filter must not become the check.
        verify_github_oidc(_token())
        _jwks.return_value.get_signing_key_from_jwt.assert_called_once()

    def test_an_expired_token_is_refused(self):
        past = datetime.now(tz=UTC) - timedelta(minutes=30)
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(exp=int(past.timestamp()), iat=int(past.timestamp())))

    @pytest.mark.parametrize("claim", ["exp", "iat", "aud", "sub"])
    def test_a_missing_required_claim_is_refused(self, claim):
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token(**{claim: None}))

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
                "repository": REPOSITORY,
                "repository_owner_id": OWNER_ID,
                "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
            },
            other,
            algorithm="RS256",
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
            "repository": REPOSITORY,
            "repository_owner_id": OWNER_ID,
            "workflow_ref": f"{WORKFLOW_PATH}@refs/heads/main",
        }

        def segment(payload: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

        signing_input = f"{segment({'alg': 'HS256', 'typ': 'JWT'})}.{segment(claims)}"
        signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
        forged = f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(forged)

    def test_an_unresolvable_signing_key_refuses(self, _jwks):
        _jwks.return_value.get_signing_key_from_jwt.side_effect = Exception("jwks unreachable")
        with pytest.raises(WizardCiOidcError):
            verify_github_oidc(_token())

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
                verify_github_oidc(_token())


class TestLooksLikeJwt:
    @pytest.mark.parametrize("token", ["a.b.c", "eyJhbGci.eyJzdWIi.sig"])
    def test_a_three_part_token_routes_here(self, token):
        assert looks_like_jwt(token)

    @pytest.mark.parametrize("token", ["pha_abc", "phx_abc", "phs_abc", "abc", "a.b", "a.b.c.d"])
    def test_a_posthog_credential_does_not(self, token):
        assert not looks_like_jwt(token)
