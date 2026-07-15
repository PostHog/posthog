from datetime import timedelta

from django.test import SimpleTestCase, override_settings

import jwt

from posthog.integration_gateway_jwt import (
    INTEGRATION_GATEWAY_AUDIENCE,
    decode_integration_gateway_jwt,
    encode_integration_gateway_jwt,
)


@override_settings(INTEGRATION_GATEWAY_JWT_SECRET="unit-test-secret")
class TestIntegrationGatewayJwt(SimpleTestCase):
    def test_round_trip_carries_scoped_claims(self):
        # Guards the exact claim shape the Rust gateway verifies (rust/integration-gateway/src/auth).
        token = encode_integration_gateway_jwt(team_id=42, caller="django", expiry_delta=timedelta(minutes=5))
        claims = decode_integration_gateway_jwt(token)
        self.assertEqual(claims["team_id"], 42)
        self.assertEqual(claims["caller"], "django")
        self.assertEqual(claims["aud"], INTEGRATION_GATEWAY_AUDIENCE)

    def test_wrong_audience_is_rejected(self):
        # A token minted for the gateway must not verify against another audience.
        token = encode_integration_gateway_jwt(team_id=1, caller="x", expiry_delta=timedelta(minutes=5))
        with self.assertRaises(jwt.InvalidAudienceError):
            jwt.decode(token, "unit-test-secret", audience="posthog:something_else", algorithms=["HS256"])

    def test_expired_token_is_rejected(self):
        token = encode_integration_gateway_jwt(team_id=1, caller="x", expiry_delta=timedelta(seconds=-1))
        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_integration_gateway_jwt(token)

    @override_settings(INTEGRATION_GATEWAY_JWT_SECRET="")
    def test_missing_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            encode_integration_gateway_jwt(team_id=1, caller="x", expiry_delta=timedelta(minutes=5))
