from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.services.email_authentication import (
    forwarder_attests_sender,
    parse_forwarder_auth_results,
)

GMAIL_AR = (
    "mx.google.com; dkim=pass header.i=@external.com header.s=sel header.b=abc123; "
    "spf=pass (google.com: domain of alice@external.com designates 1.2.3.4 as permitted sender) "
    "smtp.mailfrom=alice@external.com; "
    "dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=external.com"
)
MICROSOFT_AR = (
    "mx.microsoft.com 1; spf=pass smtp.mailfrom=external.com; "
    "dkim=pass header.d=external.com; dmarc=pass action=none header.from=external.com"
)


class TestEmailAuthentication(SimpleTestCase):
    @parameterized.expand(
        [
            # (name, ar_value, from_domain, expected_attested)
            ("gmail_format", GMAIL_AR, "external.com", True),
            ("microsoft_format_with_version", MICROSOFT_AR, "external.com", True),
            ("untrusted_authserv_id", "forwarder.example; dmarc=pass header.from=external.com", "external.com", False),
            (
                "missing_authserv_id",
                "spf=pass smtp.mailfrom=alice@external.com; dmarc=pass header.from=external.com",
                "external.com",
                False,
            ),
            ("dmarc_fail", "mx.google.com; dmarc=fail header.from=external.com", "external.com", False),
            ("header_from_misaligned", "mx.google.com; dmarc=pass header.from=evil.com", "external.com", False),
            ("no_dmarc_method", "mx.google.com; spf=pass smtp.mailfrom=alice@external.com", "external.com", False),
            (
                "subdomain_header_from_relaxed_alignment",
                "mx.google.com; dmarc=pass header.from=mail.external.com",
                "external.com",
                True,
            ),
        ]
    )
    def test_forwarder_attestation(self, _name: str, ar_value: str, from_domain: str, expected: bool):
        headers = [("Subject", "Hello"), ("Authentication-Results", ar_value)]
        attested, _ = forwarder_attests_sender(headers, from_domain)
        assert attested is expected

    def test_only_topmost_ar_header_is_trusted(self):
        # The forwarder's verdict (fail) sits above an AR header the original
        # sender injected (pass) — the injected one must be ignored.
        headers = [
            ("Authentication-Results", "mx.google.com; dmarc=fail header.from=external.com"),
            ("Authentication-Results", "mx.google.com; dmarc=pass header.from=external.com"),
        ]
        attested, _ = forwarder_attests_sender(headers, "external.com")
        assert attested is False

    def test_no_ar_header(self):
        assert parse_forwarder_auth_results([("Subject", "Hello")]) is None
        attested, authserv_id = forwarder_attests_sender([("Subject", "Hello")], "external.com")
        assert attested is False
        assert authserv_id == ""
