from datetime import UTC, datetime, timedelta

import pytest

from django.test import override_settings

import jwt

from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.session_recordings.recordings.recording_api_jwt import (
    mint_recording_api_token,
    recording_api_jwt_enabled,
    recording_api_signing_keys,
)


def _sign_with(key: str, claims: dict | None = None) -> str:
    payload = {
        "team_id": 1,
        "op": "read",
        "aud": PosthogJwtAudience.RECORDING_API.value,
        "exp": datetime.now(tz=UTC) + timedelta(minutes=5),
        **(claims or {}),
    }
    return jwt.encode(payload, key, algorithm="HS256")


class TestMintRecordingApiToken:
    @override_settings(RECORDING_API_JWT_SECRET="primary-key")
    def test_mints_team_and_op_scoped_token(self):
        token = mint_recording_api_token(123, "read")

        decoded = decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["primary-key"])

        assert decoded["team_id"] == 123
        assert decoded["op"] == "read"
        assert decoded["aud"] == "posthog:recording_api"
        assert "exp" in decoded

    @override_settings(RECORDING_API_JWT_SECRET="primary-key")
    def test_custom_ttl_is_honored(self):
        before = datetime.now(tz=UTC)
        token = mint_recording_api_token(1, "read", ttl=timedelta(minutes=70))
        decoded = decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["primary-key"])
        # exp should land ~70 minutes out — pinned to the passed ttl, not the 5-minute default or any
        # other value, so a drift in the custom ttl is caught.
        assert 69 * 60 < decoded["exp"] - before.timestamp() < 71 * 60

    @override_settings(RECORDING_API_JWT_SECRET="")
    def test_mint_without_secret_raises(self):
        with pytest.raises(RuntimeError):
            mint_recording_api_token(1, "read")

    @override_settings(RECORDING_API_JWT_SECRET="primary-key")
    def test_wrong_audience_rejected(self):
        token = mint_recording_api_token(1, "read")
        with pytest.raises(jwt.InvalidAudienceError):
            decode_jwt(token, PosthogJwtAudience.EXPORT_RENDERER, verification_keys=["primary-key"])


class TestSigningKeySelection:
    @override_settings(RECORDING_API_JWT_SECRET="new-key,old-key")
    def test_signs_with_newest_key_only(self):
        token = mint_recording_api_token(1, "delete")

        # Verifies under the newest (first) key...
        assert decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["new-key"])["op"] == "delete"
        # ...and NOT under the old key, proving we never sign with anything but the newest key.
        with pytest.raises(jwt.InvalidSignatureError):
            decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["old-key"])

    @override_settings(RECORDING_API_JWT_SECRET="new-key,old-key,")
    def test_signing_keys_drop_empty_segments_and_preserve_order(self):
        assert recording_api_signing_keys() == ["new-key", "old-key"]

    @override_settings(RECORDING_API_JWT_SECRET="only-key")
    def test_single_key_signs_and_verifies(self):
        token = mint_recording_api_token(5, "read")
        assert decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["only-key"])["team_id"] == 5


class TestRotationVerification:
    @override_settings(RECORDING_API_JWT_SECRET="new-key,old-key")
    def test_verifies_token_signed_by_newest_key(self):
        keys = recording_api_signing_keys()
        token = _sign_with("new-key")
        assert decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=keys)["team_id"] == 1

    @override_settings(RECORDING_API_JWT_SECRET="new-key,old-key")
    def test_verifies_token_signed_by_retiring_key_during_window(self):
        keys = recording_api_signing_keys()
        token = _sign_with("old-key")
        assert decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=keys)["team_id"] == 1

    @override_settings(RECORDING_API_JWT_SECRET="new-key,old-key")
    def test_rejects_token_signed_by_key_outside_the_set(self):
        keys = recording_api_signing_keys()
        token = _sign_with("attacker-key")
        with pytest.raises(jwt.InvalidSignatureError):
            decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=keys)

    @override_settings(RECORDING_API_JWT_SECRET="new-key")
    def test_rejects_retired_key_after_cleanup(self):
        # Once the old key is dropped from the set, tokens signed by it no longer verify.
        keys = recording_api_signing_keys()
        token = _sign_with("old-key")
        with pytest.raises(jwt.InvalidSignatureError):
            decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=keys)


class TestRecordingApiJwtEnabled:
    @pytest.mark.parametrize(
        "secret,expected",
        [("", False), ("a-key", True), ("new,old", True), (None, False)],
    )
    def test_enabled_reflects_configured_secret(self, secret, expected):
        with override_settings(RECORDING_API_JWT_SECRET=secret):
            assert recording_api_jwt_enabled() is expected


class TestCrossLanguageContract:
    def test_audience_literal(self):
        assert PosthogJwtAudience.RECORDING_API.value == "posthog:recording_api"

    @override_settings(RECORDING_API_JWT_SECRET="contract-key")
    def test_minted_claim_shape(self):
        decoded = decode_jwt(
            mint_recording_api_token(7, "read"), PosthogJwtAudience.RECORDING_API, verification_keys=["contract-key"]
        )
        assert decoded["team_id"] == 7
        assert decoded["op"] == "read"
        # Exactly the claims the Node verifier expects — nothing extra leaks in.
        assert set(decoded.keys()) == {"team_id", "op", "aud", "exp"}
