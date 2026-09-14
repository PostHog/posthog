import hmac

from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.pandadoc.provider import build_pandadoc_provider
from posthog.ingress.verify.schemes import VerificationOutcome

SECRET = "pandadoc-secret"
BODY = b'[{"event":"document_state_changed"}]'


def _signature() -> str:
    return hmac.digest(SECRET.encode(), BODY, "sha256").hex()


@override_settings(PANDADOC_WEBHOOK_SECRET=SECRET)
class TestPandaDocProvider(SimpleTestCase):
    @parameterized.expand(
        [
            ("header_only", _signature(), None, VerificationOutcome.VERIFIED),
            ("header_plus_an_unrelated_query_parameter", _signature(), "not-a-signature", VerificationOutcome.VERIFIED),
            ("query_parameter_only", None, _signature(), VerificationOutcome.VERIFIED),
            ("an_empty_header_does_not_fall_through", "", _signature(), VerificationOutcome.INVALID),
            ("neither", None, None, VerificationOutcome.INVALID),
        ]
    )
    def test_a_header_signature_is_never_overridden_by_the_query_parameter(
        self, _name: str, header: str | None, query_signature: str | None, expected: VerificationOutcome
    ) -> None:
        url = "/webhooks/pandadoc/"
        if query_signature is not None:
            url = f"{url}?signature={query_signature}"
        request = RequestFactory().post(
            url,
            data=BODY,
            content_type="application/json",
            headers={} if header is None else {"X-PandaDoc-Signature": header},
        )

        self.assertEqual(build_pandadoc_provider().verify(request), expected)

    def test_a_disabled_deployment_rejects_a_correctly_signed_body(self) -> None:
        request = RequestFactory().post(
            "/webhooks/pandadoc/",
            data=BODY,
            content_type="application/json",
            headers={"X-PandaDoc-Signature": _signature()},
        )

        provider = build_pandadoc_provider(enabled=lambda: False)

        self.assertEqual(provider.verify(request), VerificationOutcome.INVALID)

    def test_a_missing_secret_is_not_configured_rather_than_a_bad_signature(self) -> None:
        request = RequestFactory().post("/webhooks/pandadoc/", data=BODY, content_type="application/json")

        with override_settings(PANDADOC_WEBHOOK_SECRET=""):
            self.assertEqual(build_pandadoc_provider().verify(request), VerificationOutcome.NOT_CONFIGURED)
