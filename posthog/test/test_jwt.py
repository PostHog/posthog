from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt, signing_key_fingerprint

PRIMARY = "primary-signing-key"
ROTATED = "rotated-new-signing-key"
UNKNOWN = "never-configured-signing-key"
AUD = PosthogJwtAudience.EXPORTED_ASSET


def _raw_token(
    key: str,
    *,
    audience: PosthogJwtAudience = AUD,
    kid: str | None = None,
    expiry: timedelta = timedelta(minutes=5),
    claims: dict | None = None,
) -> str:
    payload = {**(claims or {}), "exp": datetime.now(tz=UTC) + expiry, "aud": audience.value}
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(payload, key, algorithm="HS256", headers=headers)


@override_settings(JWT_SIGNING_KEY=PRIMARY, JWT_SIGNING_KEY_FALLBACKS=[])
class TestJwt(SimpleTestCase):
    def test_encode_does_not_tag_token_with_a_key_id(self):
        # Tokens stay untagged so the header leaks nothing about which key signed them.
        token = encode_jwt({"id": 7}, timedelta(minutes=5), AUD)
        assert "kid" not in jwt.get_unverified_header(token)

    @parameterized.expand(
        [
            ("no rotation", PRIMARY, []),
            ("primary demoted to fallback after rotation", ROTATED, [PRIMARY]),
        ]
    )
    def test_encoded_token_verifies_through_rotation(self, _name: str, signing_key: str, fallbacks: list[str]):
        # Signed under the class-level PRIMARY key, then verified under the rotated settings.
        token = encode_jwt({"id": 7}, timedelta(minutes=5), AUD)
        with override_settings(JWT_SIGNING_KEY=signing_key, JWT_SIGNING_KEY_FALLBACKS=fallbacks):
            assert decode_jwt(token, AUD)["id"] == 7

    @parameterized.expand(
        [
            # name, active_signing_key, fallbacks, key_token_was_signed_with, expect_ok
            ("current signing key", PRIMARY, [], PRIMARY, True),
            ("fallback key after rotation", ROTATED, [PRIMARY], PRIMARY, True),
            ("old key dropped from fallbacks", ROTATED, [], PRIMARY, False),
            ("unknown key", PRIMARY, [], UNKNOWN, False),
        ]
    )
    def test_decode_outcome_by_key_state(
        self,
        _name: str,
        active_key: str,
        fallbacks: list[str],
        signing_key: str,
        expect_ok: bool,
    ):
        token = _raw_token(signing_key, claims={"id": 7})
        with override_settings(JWT_SIGNING_KEY=active_key, JWT_SIGNING_KEY_FALLBACKS=fallbacks):
            if expect_ok:
                assert decode_jwt(token, AUD)["id"] == 7
            else:
                with self.assertRaises(jwt.InvalidSignatureError):
                    decode_jwt(token, AUD)

    @parameterized.expand(
        [
            # A stray/forged kid must not influence verification — only the signature matters.
            ("trusted signature, forged kid", PRIMARY, True),
            ("untrusted signature, forged kid", UNKNOWN, False),
        ]
    )
    def test_decode_ignores_stray_kid_header(self, _name: str, signing_key: str, expect_ok: bool):
        token = _raw_token(signing_key, kid="some-forged-kid", claims={"id": 7})
        if expect_ok:
            assert decode_jwt(token, AUD)["id"] == 7
        else:
            with self.assertRaises(jwt.InvalidSignatureError):
                decode_jwt(token, AUD)

    @parameterized.expand(
        [
            ("expired", lambda: encode_jwt({"id": 7}, timedelta(seconds=-1), AUD), jwt.ExpiredSignatureError),
            (
                "wrong audience",
                lambda: encode_jwt({"id": 7}, timedelta(minutes=5), PosthogJwtAudience.UNSUBSCRIBE),
                jwt.InvalidAudienceError,
            ),
            ("malformed garbage", lambda: "not-a-jwt", jwt.DecodeError),
            ("malformed empty", lambda: "", jwt.DecodeError),
            ("malformed two segments", lambda: "a.b", jwt.DecodeError),
            ("malformed bad base64", lambda: "a.b.c", jwt.DecodeError),
        ]
    )
    def test_non_signature_errors_propagate(self, _name: str, token_factory, expected: type[Exception]):
        # The multi-key loop only swallows InvalidSignatureError; every other failure surfaces as-is.
        with self.assertRaises(expected):
            decode_jwt(token_factory(), AUD)

    @parameterized.expand(
        [
            ("expired", lambda: _raw_token(PRIMARY, expiry=timedelta(seconds=-1)), jwt.ExpiredSignatureError),
            (
                "wrong audience",
                lambda: _raw_token(PRIMARY, audience=PosthogJwtAudience.UNSUBSCRIBE),
                jwt.InvalidAudienceError,
            ),
        ]
    )
    @override_settings(JWT_SIGNING_KEY=ROTATED, JWT_SIGNING_KEY_FALLBACKS=[PRIMARY])
    def test_claim_errors_from_fallback_key_are_not_masked(self, _name: str, token_factory, expected: type[Exception]):
        # A token signed by the fallback key (PRIMARY) fails the InvalidSignatureError check against
        # the active key (ROTATED) first; the loop must keep going and surface the claim error raised
        # once PRIMARY matches the signature — not the earlier mismatch.
        with self.assertRaises(expected):
            decode_jwt(token_factory(), AUD)

    @parameterized.expand([("audience value", AUD.value), ("none", None), ("int", 5)])
    def test_encode_rejects_non_audience(self, _name: str, bad_audience):
        with self.assertRaises(Exception):
            encode_jwt({"id": 7}, timedelta(minutes=5), bad_audience)

    def test_signing_key_fingerprint_is_stable_and_key_specific(self):
        assert signing_key_fingerprint(PRIMARY) == signing_key_fingerprint(PRIMARY)
        assert signing_key_fingerprint(PRIMARY) != signing_key_fingerprint(ROTATED)
        assert len(signing_key_fingerprint(PRIMARY)) == 16


class TestJwtSigningKeyDefaults(SimpleTestCase):
    def test_signing_key_settings_default_to_secret_key(self):
        # With no JWT_SIGNING_KEY* env set (the test environment), JWT signing transparently
        # reuses SECRET_KEY and its fallbacks, so nothing breaks until a key is provisioned.
        assert settings.JWT_SIGNING_KEY == settings.SECRET_KEY
        assert settings.JWT_SIGNING_KEY_FALLBACKS == settings.SECRET_KEY_FALLBACKS
