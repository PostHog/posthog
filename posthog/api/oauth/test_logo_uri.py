from django.test import SimpleTestCase

from parameterized import parameterized

from .logo_uri import MAX_LOGO_URI_LENGTH, usable_logo_uri


class TestUsableLogoUri(SimpleTestCase):
    @parameterized.expand(
        [
            ("https url", "https://example.com/logo.png"),
            ("https url with query", "https://example.com/logo.png?v=2"),
        ]
    )
    def test_keeps(self, _name: str, value: str) -> None:
        self.assertEqual(usable_logo_uri(value), value)

    @parameterized.expand(
        [
            ("http", "http://example.com/logo.png"),
            ("protocol relative", "//example.com/logo.png"),
            ("data uri", "data:image/png;base64,AAAA"),
            ("javascript uri", "javascript:alert(1)"),
            ("loopback host", "https://localhost/logo.png"),
            ("loopback address", "https://127.0.0.1/logo.png"),
            ("link local address", "https://169.254.169.254/logo.png"),
            ("empty", ""),
            ("not a string", 12),
            ("missing", None),
        ]
    )
    def test_drops(self, _name: str, value: object) -> None:
        self.assertIsNone(usable_logo_uri(value))

    def test_drops_a_uri_past_the_column_limit(self) -> None:
        self.assertIsNone(usable_logo_uri("https://example.com/" + "a" * MAX_LOGO_URI_LENGTH))
