from datetime import timedelta

from django.test import SimpleTestCase, override_settings

import jwt

from posthog.integration_gateway_jwt import (
    INTEGRATION_GATEWAY_AUDIENCE,
    decode_integration_gateway_jwt,
    encode_integration_gateway_jwt,
)


class TestIntegrationGatewayJwt(SimpleTestCase):
    @override_settings(INTEGRATION_GATEWAY_JWT_SECRET="test-secret")
    def test_round_trips_team_and_caller(self) -> None:
        decoded = decode_integration_gateway_jwt(encode_integration_gateway_jwt(42, "cdp", timedelta(minutes=5)))
        assert decoded["team_id"] == 42
        assert decoded["caller"] == "cdp"
        assert decoded["aud"] == INTEGRATION_GATEWAY_AUDIENCE

    @override_settings(INTEGRATION_GATEWAY_JWT_SECRET="test-secret")
    def test_rejects_wrong_audience(self) -> None:
        token = jwt.encode(
            {"team_id": 1, "caller": "x", "aud": "posthog:something_else"}, "test-secret", algorithm="HS256"
        )
        with self.assertRaises(jwt.InvalidAudienceError):
            decode_integration_gateway_jwt(token)

    @override_settings(INTEGRATION_GATEWAY_JWT_SECRET="")
    def test_encode_fails_closed_without_secret(self) -> None:
        with self.assertRaises(RuntimeError):
            encode_integration_gateway_jwt(1, "cdp", timedelta(minutes=5))
