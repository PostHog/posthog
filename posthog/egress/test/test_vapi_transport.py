from unittest.mock import patch

from django.test import SimpleTestCase

import requests

from posthog.egress.vapi.transport import vapi_request


class TestVapiTransport(SimpleTestCase):
    def test_request_keeps_token_in_authorization_header_and_uses_fingerprint_scope(self) -> None:
        response = requests.Response()
        response.status_code = 201

        with (
            patch("posthog.egress.vapi.transport.consume_vapi_api_sync", return_value=True) as consume,
            patch("requests.request", return_value=response) as request,
            patch("posthog.egress.vapi.transport.record_vapi_api_response"),
        ):
            vapi_request(
                "POST",
                "https://api.vapi.ai/call/web",
                api_token="pk_test",
                source="user_interviews",
                endpoint="/call/web",
                json={"assistantId": "assistant"},
            )

        assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer pk_test"
        scope = consume.call_args.args[0]
        assert scope != "pk_test"
        assert len(scope) == 16
