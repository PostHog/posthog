import json
import time
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.ingress.teams.provider import build_teams_provider
from posthog.ingress.verify.jwt import _JWKS_CLIENTS
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.ingress.views import build_webhook_view

URL = "/api/conversations/v1/teams/events"
JWKS_URI = "https://login.botframework.com/v1/.well-known/keys"
APP_ID = "00000000-0000-0000-0000-000000000001"
ISSUER = "https://api.botframework.com"
SERVICE_URL = "https://smba.trafficmanager.net/teams/"
TENANT_ID = "tenant-abc"

ACTIVITY = {
    "type": "message",
    "id": "act-123",
    "text": "I have an issue",
    "serviceUrl": SERVICE_URL,
    "channelData": {"tenant": {"id": TENANT_ID}},
}


class TestTeamsProvider(SimpleTestCase):
    private_key: rsa.RSAPrivateKey

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self) -> None:
        # The client map is module-global, so a test must not inherit another test's clients.
        _JWKS_CLIENTS.clear()
        self.addCleanup(_JWKS_CLIENTS.clear)
        self.jwks_uri_calls = 0
        self.provider = build_teams_provider(
            jwks_uri_getter=self._jwks_uri,
            audience_getter=lambda: APP_ID,
            issuers_getter=lambda: frozenset({ISSUER}),
        )

    def _jwks_uri(self) -> str:
        self.jwks_uri_calls += 1
        return JWKS_URI

    def _token(self, **claims: str) -> str:
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": APP_ID,
            "serviceurl": SERVICE_URL,
            "tid": TENANT_ID,
            "exp": int(time.time()) + 300,
            **claims,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def _request(self, activity: dict[str, Any], token: str | None) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return RequestFactory().post(URL, data=json.dumps(activity), content_type="application/json", headers=headers)

    def _verify(self, request: Any) -> Any:
        # The JWKS fetch is the only boundary mocked here; the decode below it is the real one.
        signing_key = SimpleNamespace(key=self.private_key.public_key())
        with patch.object(jwt.PyJWKClient, "get_signing_key_from_jwt", return_value=signing_key):
            return self.provider.verify(request)

    def test_the_claims_a_consumer_cross_checks_the_body_against_reach_the_delivery(self) -> None:
        request = self._request(ACTIVITY, self._token())

        verification = self._verify(request)
        self.assertEqual(verification.outcome, VerificationOutcome.VERIFIED)

        deliveries = self.provider.deliveries(request, self.provider.parse(request), verification.facts)

        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        self.assertEqual(delivery.app, "supporthog")
        # The activity type, because a consumer registers for `message` or `conversationUpdate`.
        self.assertEqual(delivery.event_type, "message")
        self.assertEqual(delivery.delivery_id, "act-123")
        self.assertEqual(delivery.context["claim_tenant_id"], TENANT_ID)
        self.assertEqual(delivery.context["claim_service_url"], SERVICE_URL)
        # The token is a credential and the context travels into a consumer's logs.
        self.assertNotIn("Bearer", json.dumps(dict(delivery.context)))

    def test_an_activity_without_an_id_is_delivered_with_nothing_for_dedup_to_key_on(self) -> None:
        activity = {key: value for key, value in ACTIVITY.items() if key != "id"}
        request = self._request(activity, self._token())

        delivery = self.provider.deliveries(request, self.provider.parse(request), {})[0]

        self.assertIsNone(delivery.delivery_id)

    def test_the_throttle_refuses_a_request_before_it_buys_a_signing_key_lookup(self) -> None:
        view = build_webhook_view(self.provider)
        request = self._request(ACTIVITY, self._token())

        throttle_class = self.provider.throttle_class
        assert throttle_class is not None
        with (
            patch.object(throttle_class, "allow_request", return_value=False),
            patch.object(throttle_class, "wait", return_value=None),
        ):
            response = view(request)

        self.assertEqual(response.status_code, 429)
        # The getter is what discovers the signing keys, so an unsigned flood must not reach it.
        self.assertEqual(self.jwks_uri_calls, 0)
