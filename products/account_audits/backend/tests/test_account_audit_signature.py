import time_machine

from django.test import SimpleTestCase

from products.account_audits.backend.presentation.views import AccountAuditStartViewSet


class TestAccountAuditSignature(SimpleTestCase):
    headers = {
        "webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "webhook-timestamp": "1614265330",
        "webhook-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }

    @time_machine.travel("2021-02-25T15:02:10Z", tick=False)
    def test_accepts_standard_webhooks_reference_signature(self) -> None:
        signing_secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
        assert AccountAuditStartViewSet._valid_signature(
            signing_secret,
            b'{"test": 2432232314}',
            self.headers,
        )
        assert not AccountAuditStartViewSet._valid_signature(
            signing_secret,
            b'{"test": 2432232315}',
            self.headers,
        )

    @time_machine.travel("2021-02-25T15:10:00Z", tick=False)
    def test_rejects_an_expired_signature(self) -> None:
        signing_secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
        assert not AccountAuditStartViewSet._valid_signature(
            signing_secret,
            b'{"test": 2432232314}',
            self.headers,
        )
