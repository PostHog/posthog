import base64
import hashlib
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.api.oauth.par import PAR_REQUEST_URI_PREFIX
from posthog.models.oauth import OAuthApplication


class TestPushedAuthorizationRequest(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.confidential_application = OAuthApplication.objects.create(
            name="Test Confidential App",
            client_id="test_confidential_client_id",
            client_secret="test_confidential_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        self.public_application = OAuthApplication.objects.create(
            name="Test Public App",
            client_id="test_public_client_id",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        self.client.force_login(self.user)

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(b"test_challenge").digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")

    def push(self, body: dict):
        return self.client.post("/oauth/par/", data=urlencode(body), content_type="application/x-www-form-urlencoded")

    def public_par_body(self) -> dict:
        return {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "scope": "openid",
        }

    def test_public_client_push_returns_request_uri(self):
        response = self.push(self.public_par_body())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data["request_uri"].startswith(PAR_REQUEST_URI_PREFIX))
        self.assertGreater(data["expires_in"], 0)

    def test_confidential_client_requires_valid_secret(self):
        body = self.public_par_body()
        body["client_id"] = "test_confidential_client_id"

        # Missing secret is rejected
        self.assertEqual(self.push(body).status_code, status.HTTP_401_UNAUTHORIZED)

        # Wrong secret is rejected
        body["client_secret"] = "wrong"
        self.assertEqual(self.push(body).status_code, status.HTTP_401_UNAUTHORIZED)

        # Correct secret succeeds
        body["client_secret"] = "test_confidential_client_secret"
        self.assertEqual(self.push(body).status_code, status.HTTP_201_CREATED)

    def test_confidential_client_authenticates_with_http_basic(self):
        # A confidential client using client_secret_basic sends its credentials in
        # the Authorization header, not the form body — same as /oauth/token/.
        body = self.public_par_body()
        body.pop("client_id")
        credentials = base64.b64encode(b"test_confidential_client_id:test_confidential_client_secret").decode()

        response = self.client.post(
            "/oauth/par/",
            data=urlencode(body),
            content_type="application/x-www-form-urlencoded",
            HTTP_AUTHORIZATION=f"Basic {credentials}",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_first_use_cimd_client_is_provisioned(self):
        # A CIMD (URL-form) client_id has no pre-registration: first use provisions
        # it. The push must provision it like /oauth/authorize/ does, rather than
        # 401 because no OAuthApplication row exists yet.
        cimd_client_id = "https://example.com/.well-known/oauth-client"
        # The provisioned row is deliberately NOT keyed on cimd_client_id, so the
        # plain get_application_by_client_id lookup would miss it — only the
        # provisioning path (mocked below) can resolve the client. That's what
        # distinguishes the fixed behavior from the first-use 401 regression.
        provisioned = OAuthApplication.objects.create(
            name="CIMD App",
            client_id="cimd_internal_client_id",
            cimd_metadata_url="https://provisioned.example.com/.well-known/oauth-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        body = self.public_par_body()
        body["client_id"] = cimd_client_id

        with patch("posthog.api.oauth.par.get_or_create_cimd_application", return_value=provisioned) as mock_provision:
            response = self.push(body)

        mock_provision.assert_called_once_with(cimd_client_id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_first_use_cimd_push_is_rate_limited(self):
        # First-use CIMD provisioning triggers an outbound metadata fetch, so the
        # push must hit the same CIMD creation throttles as /oauth/authorize/
        # before any provisioning work runs — not just the looser PAR IP limit.
        mock_throttle = MagicMock()
        mock_throttle.allow_request.return_value = False
        mock_throttle.wait.return_value = 30
        mock_throttle.scope = "cimd_burst"
        mock_throttle_cls = MagicMock(return_value=mock_throttle)

        body = self.public_par_body()
        body["client_id"] = "https://new-client.example.com/.well-known/oauth-client"

        with (
            patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[mock_throttle_cls]),
            patch("posthog.api.oauth.par.get_or_create_cimd_application") as mock_provision,
        ):
            response = self.push(body)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_provision.assert_not_called()

    def test_unknown_client_is_rejected(self):
        body = self.public_par_body()
        body["client_id"] = "does_not_exist"

        self.assertEqual(self.push(body).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_request_uri_param_is_rejected(self):
        body = self.public_par_body()
        body["request_uri"] = f"{PAR_REQUEST_URI_PREFIX}anything"

        response = self.push(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_authorize_expands_pushed_parameters(self):
        # Push a full authorization request, then start the browser flow carrying
        # only client_id + request_uri. The authorize endpoint must redirect to
        # itself with the pushed parameters expanded into the query string (so the
        # consent SPA can build its approve POST), dropping request_uri.
        request_uri = self.push(self.public_par_body()).json()["request_uri"]

        response = self.client.get(
            f"/oauth/authorize/?client_id=test_public_client_id&{urlencode({'request_uri': request_uri})}"
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        location = response["Location"]
        self.assertIn("redirect_uri=", location)
        self.assertIn("code_challenge=", location)
        self.assertIn("scope=", location)
        self.assertNotIn("request_uri=", location)

        # Following the expanded URL renders the consent screen.
        followed = self.client.get(location)
        self.assertEqual(followed.status_code, status.HTTP_200_OK)

    def test_authorize_rejects_request_uri_without_client_id(self):
        # RFC 9126 §4: the authorization request must identify the client the
        # reference was issued to. A request_uri presented without client_id is
        # rejected rather than restoring the client_id from the pushed params.
        request_uri = self.push(self.public_par_body()).json()["request_uri"]

        response = self.client.get(f"/oauth/authorize/?{urlencode({'request_uri': request_uri})}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_push_rejects_oversized_request(self):
        body = self.public_par_body()
        body["scope"] = "a" * (40 * 1024)  # over PAR_MAX_STORED_BYTES

        response = self.push(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_authorize_rejects_unknown_request_uri(self):
        response = self.client.get(
            f"/oauth/authorize/?client_id=test_public_client_id"
            f"&{urlencode({'request_uri': f'{PAR_REQUEST_URI_PREFIX}nonexistent'})}"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_authorize_rejects_request_uri_bound_to_other_client(self):
        # A request_uri pushed by the public client cannot be replayed by another client.
        request_uri = self.push(self.public_par_body()).json()["request_uri"]

        response = self.client.get(
            f"/oauth/authorize/?client_id=test_confidential_client_id&{urlencode({'request_uri': request_uri})}"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
