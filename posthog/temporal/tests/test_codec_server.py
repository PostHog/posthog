import os

from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase

from google.protobuf import json_format
from temporalio.api.common.v1 import Payload, Payloads

from posthog.temporal.common.codec import EncryptionCodec


class CodecServerTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.codec = EncryptionCodec(settings)
        # Set up test auth token
        self.test_token = "test-codec-auth-token"
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.test_token}"}

    def test_decode_endpoint_handles_options(self):
        response = self.client.options("/decode", HTTP_ORIGIN="https://temporal-ui.posthog.orb.local")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://temporal-ui.posthog.orb.local")
        self.assertEqual(response["Access-Control-Allow-Methods"], "POST, OPTIONS")

    @patch.dict(os.environ, {"TEMPORAL_CODEC_AUTH_TOKEN": "test-codec-auth-token"})
    def test_decode_empty_payloads(self):
        payloads = Payloads(payloads=[])
        request_data = json_format.MessageToJson(payloads)

        response = self.client.post(
            "/decode",
            request_data,
            content_type="application/json",
            **self.auth_headers,
            HTTP_ORIGIN="https://temporal-ui.posthog.orb.local",
        )
        self.assertEqual(response.status_code, 200)

        response_payloads = json_format.Parse(response.content, Payloads())
        self.assertEqual(len(response_payloads.payloads), 0)

    @patch.dict(os.environ, {"TEMPORAL_CODEC_AUTH_TOKEN": "test-codec-auth-token"})
    def test_decode_encrypted_payload(self):
        original_payload = Payload(metadata={"encoding": b"json/plain"}, data=b'{"test": "data"}')
        encrypted_data = self.codec.encrypt(original_payload.SerializeToString())

        encrypted_payload = Payload(metadata={"encoding": b"binary/encrypted"}, data=encrypted_data)

        payloads = Payloads(payloads=[encrypted_payload])
        request_data = json_format.MessageToJson(payloads)

        response = self.client.post(
            "/decode",
            request_data,
            content_type="application/json",
            **self.auth_headers,
            HTTP_ORIGIN="https://temporal-ui.posthog.orb.local",
        )

        self.assertEqual(response.status_code, 200)

        response_payloads = json_format.Parse(response.content, Payloads())
        self.assertEqual(len(response_payloads.payloads), 1)

        decoded_payload = response_payloads.payloads[0]
        self.assertEqual(decoded_payload.metadata["encoding"], b"json/plain")
        self.assertEqual(decoded_payload.data, b'{"test": "data"}')

    @patch.dict(os.environ, {"TEMPORAL_CODEC_AUTH_TOKEN": "test-codec-auth-token"})
    def test_decode_unauthorized_without_token(self):
        """Test that requests without proper authorization are rejected."""
        payloads = Payloads(payloads=[])
        request_data = json_format.MessageToJson(payloads)

        # Test without any auth header when token is required
        response = self.client.post(
            "/decode",
            request_data,
            content_type="application/json",
            HTTP_ORIGIN="https://temporal-ui.posthog.orb.local",
        )
        # Should be rejected when token is configured but not provided
        self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {"TEMPORAL_CODEC_AUTH_TOKEN": "test-codec-auth-token"})
    def test_decode_unauthorized_with_wrong_token(self):
        """Test that requests with wrong token are rejected."""
        payloads = Payloads(payloads=[])
        request_data = json_format.MessageToJson(payloads)

        # Test with wrong token
        response = self.client.post(
            "/decode",
            request_data,
            content_type="application/json",
            HTTP_ORIGIN="https://temporal-ui.posthog.orb.local",
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unauthorized", response.content.decode())
