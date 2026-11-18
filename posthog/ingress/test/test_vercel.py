import hmac
import json

from unittest.mock import patch

from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.vercel.provider import (
    RECEIVING_REGION_CONTEXT_KEY,
    VERCEL_BILLING_EVENT,
    VERCEL_DEAUTHORIZATION_EVENT,
    build_vercel_provider,
)
from posthog.ingress.verify.schemes import VerificationOutcome

SECRET = "vercel-integration-client-secret"


def _request(body: bytes, *, signed: bool = True, host: str | None = None) -> HttpRequest:
    headers = {"x-vercel-signature": hmac.digest(SECRET.encode(), body, "sha1").hex()} if signed else {}
    if host is not None:
        headers["Host"] = host
    return RequestFactory().post("/webhooks/vercel", data=body, content_type="application/json", headers=headers)


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET=SECRET)
class TestVercelProvider(SimpleTestCase):
    def setUp(self) -> None:
        self.provider = build_vercel_provider()
        self.body = json.dumps({"type": "marketplace.invoice.paid", "payload": {"installationId": "icfg_1"}}).encode()

    def test_the_signature_is_hmac_sha1_over_the_raw_body(self) -> None:
        # Vercel signs with SHA-1, which no other provider here does, so a digest default that
        # silently applied would refuse every real delivery.
        verified = self.provider.verify(_request(self.body))
        refused = self.provider.verify(_request(self.body, signed=False))

        self.assertEqual(verified.outcome, VerificationOutcome.VERIFIED)
        self.assertEqual(refused.outcome, VerificationOutcome.INVALID)

    def test_the_forward_waits_longer_than_the_billing_call_it_may_be_waiting_on(self) -> None:
        # The owning region blocks up to 30 s on the billing service, so a shorter deadline here
        # makes the receiving region give up on an invoice the other region is still processing.
        self.assertGreater(self.provider.forward_timeout_seconds, 30)

    def test_a_missing_secret_is_reported_rather_than_only_refused(self) -> None:
        # Both a bad signature and a missing secret answer 401, so nothing in the status code
        # distinguishes a dropped secret from a stranger probing the endpoint.
        self.assertTrue(self.provider.reports_unconfigured)
        self.assertEqual(self.provider.unconfigured_status, 401)
        self.assertEqual(self.provider.invalid_signature_status, 401)

    @parameterized.expand(
        [
            ("paid", "marketplace.invoice.paid", VERCEL_BILLING_EVENT),
            ("refunded", "marketplace.invoice.refunded", VERCEL_BILLING_EVENT),
            # A family member Vercel has not shipped yet still reaches the one consumer.
            ("unseen_member", "marketplace.invoice.disputed", VERCEL_BILLING_EVENT),
            ("deauthorization", VERCEL_DEAUTHORIZATION_EVENT, VERCEL_DEAUTHORIZATION_EVENT),
            ("unrelated", "deployment.created", "deployment.created"),
        ]
    )
    def test_the_invoice_family_collapses_to_one_registered_event_type(
        self, _name: str, sent: str, expected: str
    ) -> None:
        body = json.dumps({"type": sent, "payload": {}}).encode()

        deliveries = self.provider.deliveries(_request(body), json.loads(body), {})

        self.assertEqual([delivery.event_type for delivery in deliveries], [expected])

    def test_the_whole_envelope_travels_so_the_consumer_can_read_the_exact_event_name(self) -> None:
        deliveries = self.provider.deliveries(_request(self.body), json.loads(self.body), {})

        self.assertEqual(deliveries[0].payload["type"], "marketplace.invoice.paid")
        self.assertIsNone(deliveries[0].delivery_id)

    @parameterized.expand([("receiving", "us.posthog.com", "true"), ("other", "eu.posthog.com", "false")])
    def test_a_delivery_says_whether_it_arrived_in_the_region_that_forwards(
        self, _name: str, host: str, expected: str
    ) -> None:
        # The consumer reports an installation no region holds at warning level only in the
        # region that looks last, and this flag is how it tells the two apart.
        request = _request(self.body, host=host)

        with (
            patch("posthog.regions.SECONDARY_REGION_DOMAIN", "us.posthog.com"),
            override_settings(ALLOWED_HOSTS=["us.posthog.com", "eu.posthog.com"]),
        ):
            deliveries = self.provider.deliveries(request, json.loads(self.body), {})

        self.assertEqual(deliveries[0].context[RECEIVING_REGION_CONTEXT_KEY], expected)

    def test_a_body_that_is_not_an_object_becomes_no_delivery(self) -> None:
        # Vercel always sends an object. A verified body that is not one names no event, so there
        # is nothing to dispatch and nothing a redelivery could fix.
        self.assertEqual(self.provider.deliveries(_request(b"[]"), [], {}), ())
