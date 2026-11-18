from posthog.test.base import APIBaseTest

from django.core.cache import cache

from parameterized import parameterized

from posthog.api.oauth.cimd import _verification_rejected_capture_key
from posthog.models.oauth import create_cimd_verification_token

CIMD_URL = "https://app.example.com/.well-known/oauth-client-metadata.json"
CHECK_URL = "/oauth/cimd/verification-token-check/"


class TestCIMDVerificationCheck(APIBaseTest):
    @parameterized.expand(
        [
            ("issued_for_this_url", None, CIMD_URL, True),
            ("copied_into_another_document", None, "https://evil.example.com/client.json", False),
            ("unknown_token", "phvt_never_issued", CIMD_URL, False),
        ]
    )
    def test_answers_whether_the_token_is_valid_for_the_url(self, _name, token, cimd_url, expected):
        issued, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Partner", cimd_url=CIMD_URL, created_by=self.user
        )
        self.client.logout()

        response = self.client.post(CHECK_URL, {"token": token or plaintext, "cimd_url": cimd_url}, format="json")

        assert response.status_code == 200, response.content
        assert response.json() == {"valid": expected}
        assert cache.get(_verification_rejected_capture_key(issued, cimd_url, "url_mismatch")) is None
