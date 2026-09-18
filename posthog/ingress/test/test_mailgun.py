import hmac
import time
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.mailgun.provider import FILES_KEY, MAX_FILES, MailgunProvider, build_mailgun_provider
from posthog.ingress.providers import InvalidPayload
from posthog.ingress.verify.schemes import VerificationOutcome

SIGNING_KEY = "mailgun-signing-key"
URL = "/api/conversations/v1/email/inbound"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


def _signed_fields(*, age_seconds: int = 0, token: str = "delivery-token") -> dict[str, str]:
    timestamp = str(int(time.time()) - age_seconds)
    signature = hmac.digest(SIGNING_KEY.encode(), f"{timestamp}{token}".encode(), "sha256").hex()
    return {"timestamp": timestamp, "token": token, "signature": signature}


def _provider(app: str = "inbound", *, signing_key: str | None = SIGNING_KEY) -> MailgunProvider:
    return build_mailgun_provider(app, signing_key_getter=lambda: signing_key)


class TestMailgunProvider(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_fresh_signed_form", 0, {}, SIGNING_KEY, VerificationOutcome.VERIFIED),
            ("a_wrong_signature", 0, {"signature": "f" * 64}, SIGNING_KEY, VerificationOutcome.INVALID),
            ("a_token_swapped_after_signing", 0, {"token": "other"}, SIGNING_KEY, VerificationOutcome.INVALID),
            ("a_stale_timestamp", 600, {}, SIGNING_KEY, VerificationOutcome.INVALID),
            ("no_signing_key", 0, {}, None, VerificationOutcome.NOT_CONFIGURED),
        ]
    )
    def test_verification_reads_the_signature_out_of_the_form(
        self,
        _name: str,
        age_seconds: int,
        overrides: dict[str, str],
        signing_key: str | None,
        expected: VerificationOutcome,
    ) -> None:
        fields = _signed_fields(age_seconds=age_seconds) | overrides
        request = RequestFactory().post(URL, data=urlencode(fields), content_type=FORM_CONTENT_TYPE)

        self.assertEqual(_provider(signing_key=signing_key).verify(request).outcome, expected)

    def test_a_multipart_delivery_verifies_and_parses_into_the_form_fields_and_its_files(self) -> None:
        fields = _signed_fields()
        request = RequestFactory().post(
            URL,
            data={
                **fields,
                "recipient": "team-abc@example.com",
                "body-plain": "hello",
                "attachment-1": SimpleUploadedFile("note.txt", b"attached", content_type="text/plain"),
            },
        )
        provider = _provider()

        self.assertEqual(provider.verify(request).outcome, VerificationOutcome.VERIFIED)

        payload = provider.parse(request)
        self.assertEqual(payload["recipient"], "team-abc@example.com")
        self.assertEqual(payload["body-plain"], "hello")
        self.assertEqual(payload["token"], fields["token"])
        self.assertEqual(list(payload[FILES_KEY]), ["attachment-1"])
        self.assertEqual(payload[FILES_KEY]["attachment-1"].read(), b"attached")

        (delivery,) = provider.deliveries(request, payload, {})
        self.assertEqual(delivery.delivery_id, fields["token"])

    @parameterized.expand([("inbound", "message_received"), ("outbound", "message_sent")])
    def test_each_app_types_its_delivery_by_the_route_it_serves(self, app: str, event_type: str) -> None:
        request = RequestFactory().post(URL, data=urlencode(_signed_fields()), content_type=FORM_CONTENT_TYPE)
        provider = _provider(app)

        (delivery,) = provider.deliveries(request, provider.parse(request), {})

        self.assertEqual((delivery.app, delivery.event_type), (app, event_type))

    def test_a_body_that_is_not_a_form_is_refused_rather_than_read_as_one(self) -> None:
        request = RequestFactory().post(URL, data='{"token": "delivery-token"}', content_type="application/json")
        provider = _provider()

        self.assertEqual(provider.verify(request).outcome, VerificationOutcome.INVALID)
        with self.assertRaises(InvalidPayload):
            provider.parse(request)

    def test_the_number_of_files_one_delivery_can_carry_is_capped(self) -> None:
        files = {
            f"attachment-{index}": SimpleUploadedFile(f"{index}.txt", b"attached", content_type="text/plain")
            for index in range(MAX_FILES + 5)
        }
        request = RequestFactory().post(URL, data={**_signed_fields(), **files})

        payload = _provider().parse(request)

        self.assertEqual(len(payload[FILES_KEY]), MAX_FILES)

    def test_an_unknown_app_is_refused_at_build(self) -> None:
        with self.assertRaises(ValueError):
            _provider("events")
