import json
import time
from types import SimpleNamespace
from typing import Any

from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.ingress.contracts import DeliveryDispatch, DeliveryOwnership
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

TEAMS_ENDORSED_KEY = {"endorsements": ["msteams"]}

ACTIVITY = {
    "type": "message",
    "id": "act-123",
    "channelId": "msteams",
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
        self.dispatcher = Mock()
        self.dispatcher.ownership_of.return_value = (DeliveryOwnership.UNDECIDED, ())
        self.dispatcher.dispatch.return_value = DeliveryDispatch()
        patcher = patch("posthog.ingress.views.get_dispatcher", return_value=self.dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _jwks_uri(self) -> str:
        self.jwks_uri_calls += 1
        return JWKS_URI

    def _token(self, **claims: Any) -> str:
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": APP_ID,
            "serviceurl": SERVICE_URL,
            "tid": TENANT_ID,
            "exp": int(time.time()) + 300,
            **claims,
        }
        present = {key: value for key, value in payload.items() if value is not None}
        return jwt.encode(present, self.private_key, algorithm="RS256")

    def _request(self, activity: dict[str, Any], token: str | None) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return RequestFactory().post(URL, data=json.dumps(activity), content_type="application/json", headers=headers)

    def _signing_key(self, jwk: dict[str, Any] | None = None) -> Any:
        # The JWKS fetch is the only boundary mocked here; the decode below it is the real one.
        key = SimpleNamespace(
            key=self.private_key.public_key(),
            _jwk_data=TEAMS_ENDORSED_KEY if jwk is None else jwk,
        )
        return patch.object(jwt.PyJWKClient, "get_signing_key_from_jwt", return_value=key)

    def _deliveries(self, activity: dict[str, Any], token: str) -> Any:
        request = self._request(activity, token)
        with self._signing_key():
            verification = self.provider.verify(request)
        self.assertEqual(verification.outcome, VerificationOutcome.VERIFIED)
        return self.provider.deliveries(request, self.provider.parse(request), verification.facts)

    def _view_response(self, activity: dict[str, Any], token: str, jwk: dict[str, Any] | None = None) -> Any:
        with self._signing_key(jwk):
            return build_webhook_view(self.provider)(self._request(activity, token))

    def test_the_claims_a_consumer_reads_reach_the_delivery(self) -> None:
        deliveries = self._deliveries(ACTIVITY, self._token())

        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        self.assertEqual(delivery.app, "supporthog")
        # The activity type, because a consumer registers for `message` or `conversationUpdate`.
        self.assertEqual(delivery.event_type, "message")
        self.assertEqual(delivery.delivery_id, "act-123")
        self.assertEqual(delivery.context["claim_tenant_id"], TENANT_ID)
        self.assertEqual(delivery.context["claim_service_url"], SERVICE_URL.rstrip("/"))
        # The token is a credential and the context travels into a consumer's logs.
        self.assertNotIn("Bearer", json.dumps(dict(delivery.context)))

    @parameterized.expand(
        [
            # Bot Framework requires the claim, and the bot sends its bearer token to whatever
            # the body names, so a token without it must not choose that host.
            ("a token that carries no serviceurl claim", {"serviceurl": None}, {}, None),
            ("a serviceUrl the claim does not name", {}, {"serviceUrl": "https://attacker.example.com/"}, None),
            ("an empty serviceUrl", {}, {"serviceUrl": ""}, None),
            ("a tenant the claim does not name", {}, {"channelData": {"tenant": {"id": "other-tenant"}}}, None),
            ("an activity from another channel", {}, {"channelId": "directline"}, None),
            ("an activity that names no channel", {}, {"channelId": ""}, None),
            ("a key endorsed for another channel", {}, {}, {"endorsements": ["directline"]}),
            ("a key that carries no endorsements", {}, {}, {}),
        ]
    )
    def test_an_activity_the_token_does_not_back_is_refused_before_dispatch(
        self, _name: str, claims: dict[str, Any], activity_overrides: dict[str, Any], jwk: dict[str, Any] | None
    ) -> None:
        response = self._view_response({**ACTIVITY, **activity_overrides}, self._token(**claims), jwk=jwk)

        self.assertEqual(response.status_code, 400)
        self.dispatcher.ownership_of.assert_not_called()
        self.dispatcher.dispatch.assert_not_called()

    @parameterized.expand(
        [
            # Microsoft's own SDKs compare the two as strings without regard to case.
            ("a claim in another case", "https://SMBA.trafficmanager.net/teams/"),
            # Teams sends the URL with a trailing slash in the body and without one in the claim.
            ("a claim without the body's trailing slash", "https://smba.trafficmanager.net/teams"),
        ]
    )
    def test_a_claim_that_names_the_same_url_is_accepted(self, _name: str, claim_service_url: str) -> None:
        deliveries = self._deliveries(ACTIVITY, self._token(serviceurl=claim_service_url))

        self.assertEqual(len(deliveries), 1)
        # The body's spelling, because that is what the consumer sends the bot's token to.
        self.assertEqual(deliveries[0].context["claim_service_url"], SERVICE_URL.rstrip("/"))

    def test_an_activity_without_an_id_is_delivered_with_nothing_for_dedup_to_key_on(self) -> None:
        activity = {key: value for key, value in ACTIVITY.items() if key != "id"}

        delivery = self._deliveries(activity, self._token())[0]

        self.assertIsNone(delivery.delivery_id)

    def test_the_throttle_refuses_a_request_before_it_buys_a_signing_key_lookup(self) -> None:
        throttle_class = self.provider.throttle_class
        assert throttle_class is not None

        with (
            patch.object(throttle_class, "allow_request", return_value=False),
            patch.object(throttle_class, "wait", return_value=None),
        ):
            response = self._view_response(ACTIVITY, self._token())

        self.assertEqual(response.status_code, 429)
        # The getter is what discovers the signing keys, so an unsigned flood must not reach it.
        self.assertEqual(self.jwks_uri_calls, 0)

    def _unconfigured_view_response(self, *, jwks_uri: str | None, audience: str | None) -> Any:
        provider = build_teams_provider(
            jwks_uri_getter=lambda: jwks_uri,
            audience_getter=lambda: audience,
            issuers_getter=lambda: frozenset({ISSUER}),
        )
        throttle_class = provider.throttle_class
        assert throttle_class is not None

        # The throttle keys on the caller and its cache is shared with every other test in this
        # process, so the cap is held open rather than left to test order.
        with patch.object(throttle_class, "allow_request", return_value=True):
            return build_webhook_view(provider)(self._request(ACTIVITY, self._token()))

    def test_an_unset_app_id_answers_403_with_no_reason(self) -> None:
        # The package default is 500, which would turn every anonymous probe of this public URL
        # into a server error on an instance that never registered a bot. The endpoint answered
        # 403 before it moved into this package.
        response = self._unconfigured_view_response(jwks_uri=JWKS_URI, audience=None)

        self.assertEqual(response.status_code, 403)
        # And the body must not tell that caller whether the instance is merely unconfigured.
        self.assertEqual(response.content, b"")

    def test_a_signing_key_uri_that_could_not_be_discovered_answers_503(self) -> None:
        # The getter fetches Microsoft's OpenID metadata and answers None when that fetch fails.
        # Reading that as unconfigured would answer 403, which Bot Framework does not retry, and
        # a metadata outage would then lose every activity in it.
        response = self._unconfigured_view_response(jwks_uri=None, audience=APP_ID)

        self.assertEqual(response.status_code, 503)
