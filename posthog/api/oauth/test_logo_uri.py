import ipaddress

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from .logo_uri import MAX_LOGO_URI_LENGTH, usable_logo_uri

PUBLIC_IPS = {ipaddress.ip_address("93.184.216.34")}
PRIVATE_IPS = {ipaddress.ip_address("10.1.2.3")}


class TestUsableLogoUri(SimpleTestCase):
    @parameterized.expand(
        [
            ("https url", "https://example.com/logo.png"),
            ("https url with query", "https://example.com/logo.png?v=2"),
        ]
    )
    def test_keeps(self, _name: str, value: str) -> None:
        with patch("posthog.security.url_validation.resolve_host_ips", return_value=PUBLIC_IPS):
            self.assertEqual(usable_logo_uri(value), value)

    @parameterized.expand(
        [
            ("http", "http://example.com/logo.png"),
            ("protocol relative", "//example.com/logo.png"),
            ("data uri", "data:image/png;base64,AAAA"),
            ("javascript uri", "javascript:alert(1)"),
            ("loopback host", "https://localhost/logo.png"),
            ("loopback address", "https://127.0.0.1/logo.png"),
            ("private address", "https://10.0.0.5/logo.png"),
            ("link local metadata address", "https://169.254.169.254/logo.png"),
            ("internal domain suffix", "https://billing.svc.cluster.local/logo.png"),
            ("empty", ""),
            ("not a string", 12),
            ("missing", None),
        ]
    )
    def test_drops(self, _name: str, value: object) -> None:
        with patch("posthog.security.url_validation.resolve_host_ips", return_value=PUBLIC_IPS):
            self.assertIsNone(usable_logo_uri(value))

    def test_drops_a_public_name_that_resolves_to_a_private_address(self) -> None:
        with patch("posthog.security.url_validation.resolve_host_ips", return_value=PRIVATE_IPS):
            self.assertIsNone(usable_logo_uri("https://logo.example.com/logo.png"))

    def test_drops_a_uri_past_the_column_limit(self) -> None:
        self.assertIsNone(usable_logo_uri("https://example.com/" + "a" * MAX_LOGO_URI_LENGTH))
