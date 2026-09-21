import hmac

from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.vercel.provider import build_vercel_provider
from posthog.ingress.verify.schemes import VerificationOutcome

SECRET = "vercel-secret"
BODY = b'{"type":"marketplace.invoice.paid","payload":{"installationId":"icfg_1"}}'


def _sha1_signature() -> str:
    return hmac.digest(SECRET.encode(), BODY, "sha1").hex()


def _sha256_signature() -> str:
    return hmac.digest(SECRET.encode(), BODY, "sha256").hex()


def _request(signature: str | None):
    return RequestFactory().post(
        "/webhooks/vercel",
        data=BODY,
        content_type="application/json",
        headers={} if signature is None else {"x-vercel-signature": signature},
    )


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET=SECRET)
class TestVercelProvider(SimpleTestCase):
    @parameterized.expand(
        [
            ("sha1_is_the_digest_vercel_signs_with", _sha1_signature(), VerificationOutcome.VERIFIED),
            ("the_package_default_sha256_does_not_pass", _sha256_signature(), VerificationOutcome.INVALID),
            ("no_signature_header", None, VerificationOutcome.INVALID),
        ]
    )
    def test_the_digest_decides(self, _name: str, signature: str | None, expected: VerificationOutcome) -> None:
        self.assertEqual(build_vercel_provider().verify(_request(signature)).outcome, expected)

    def test_a_missing_secret_is_not_configured_rather_than_a_bad_signature(self) -> None:
        with override_settings(VERCEL_CLIENT_INTEGRATION_SECRET=""):
            outcome = build_vercel_provider().verify(_request(_sha1_signature())).outcome

        self.assertEqual(outcome, VerificationOutcome.NOT_CONFIGURED)

    @parameterized.expand(
        [
            ("an_invoice_event_collapses_to_the_family", "marketplace.invoice.notpaid", "marketplace.invoice"),
            (
                "deauthorization_keeps_its_own_name",
                "integration-configuration.removed",
                "integration-configuration.removed",
            ),
            ("anything_else_passes_through", "deployment.created", "deployment.created"),
        ]
    )
    def test_the_invoice_family_is_registered_under_one_name(self, _name: str, sent: str, expected: str) -> None:
        payload = {"type": sent, "payload": {"installationId": "icfg_1"}}

        deliveries = build_vercel_provider().deliveries(_request(None), payload, {})

        self.assertEqual([delivery.event_type for delivery in deliveries], [expected])
        # The exact name the billing service routes on stays readable on the delivery.
        self.assertEqual(deliveries[0].payload["type"], sent)
