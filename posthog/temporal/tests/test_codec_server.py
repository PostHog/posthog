import json
import base64

from django.conf import settings
from django.test import Client, TestCase

from temporalio.api.common.v1 import Payload

from posthog.temporal.common.codec import EncryptionCodec


class CodecServerTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.codec = EncryptionCodec(settings)

    def test_decode_endpoint_handles_options(self):
        response = self.client.options("/decode")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://temporal-ui.posthog.orb.local")
        self.assertEqual(response["Access-Control-Allow-Methods"], "POST, OPTIONS")

    def test_decode_empty_payloads(self):
        response = self.client.post("/decode", json.dumps({"payloads": []}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data, {"payloads": []})

    def test_decode_encrypted_payload(self):
        original_payload = Payload(metadata={"encoding": b"json/plain"}, data=b'{"test": "data"}')

        encrypted_data = self.codec.encrypt(original_payload.SerializeToString())

        request_payload = {
            "payloads": [
                {
                    "metadata": {"encoding": base64.b64encode(b"binary/encrypted").decode("utf-8")},
                    "data": base64.b64encode(encrypted_data).decode("utf-8"),
                }
            ]
        }

        response = self.client.post("/decode", json.dumps(request_payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertEqual(len(data["payloads"]), 1)
        decoded_payload = data["payloads"][0]

        self.assertIn("metadata", decoded_payload)
        self.assertEqual(base64.b64decode(decoded_payload["metadata"]["encoding"]), b"json/plain")

        self.assertEqual(base64.b64decode(decoded_payload["data"]), b'{"test": "data"}')
