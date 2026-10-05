import json
from urllib.parse import quote

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.oauth_pending_connection import PendingOAuthConnection


class TestPendingOAuthConnectionCookieValue(SimpleTestCase):
    def test_round_trip_keeps_every_field(self):
        connection = PendingOAuthConnection(
            client_name="Claude &amp; Co",
            client_id="https://claude.example.com/.well-known/oauth-client",
            logo_uri="https://claude.example.com/logo.png",
            redirect_host="claude.example.com",
        )

        self.assertEqual(PendingOAuthConnection.from_cookie_value(connection.to_cookie_value()), connection)

    def test_round_trip_drops_an_oversized_logo_but_keeps_the_rest(self):
        connection = PendingOAuthConnection(
            client_name="Cursor", client_id="cursor_client_id", logo_uri="https://example.com/" + "a" * 2000
        )

        restored = PendingOAuthConnection.from_cookie_value(connection.to_cookie_value())

        self.assertEqual(restored, PendingOAuthConnection(client_name="Cursor", client_id="cursor_client_id"))

    @parameterized.expand(
        [
            ("missing", None),
            ("empty", ""),
            ("not_json", "not%20json"),
            ("not_an_object", quote("[]")),
            ("missing_client_name", quote(json.dumps({"client_id": "x"}))),
            ("wrong_type", quote(json.dumps({"client_name": 5, "client_id": "x"}))),
            ("oversized_client_name", quote(json.dumps({"client_name": "a" * 256, "client_id": "x"}))),
        ]
    )
    def test_forged_or_malformed_values_read_as_absent(self, _name, raw):
        self.assertIsNone(PendingOAuthConnection.from_cookie_value(raw))
