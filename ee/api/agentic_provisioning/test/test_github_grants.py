from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.integration import GitHubUserAuthorization
from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning import GITHUB_GRANT_CACHE_PREFIX, github_grants
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase

ACCESS_TOKEN = "gho_secret_user_token"

AUTHORIZATION = GitHubUserAuthorization(
    gh_id=12345,
    gh_login="octocat",
    access_token=ACCESS_TOKEN,
    refresh_token="ghr_refresh_token",
    access_token_expires_in=28800,
    refresh_token_expires_in=15897600,
)


def _github_response(status_code: int, payload: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


EMAILS_RESPONSE = _github_response(
    200,
    [
        {"email": "secondary@example.com", "primary": False, "verified": True},
        {"email": "octocat@example.com", "primary": True, "verified": True},
        {"email": "unverified@example.com", "primary": False, "verified": False},
    ],
)

INSTALLATIONS_RESPONSE = _github_response(
    200,
    {
        "installations": [
            {"id": 777, "account": {"login": "octocat"}, "repository_selection": "selected"},
        ]
    },
)

REPOSITORIES_RESPONSE = _github_response(
    200,
    {
        "repositories": [
            {"full_name": "octocat/hello-world", "default_branch": "main", "private": False},
        ]
    },
)


class TestGitHubGrants(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.partner = OAuthApplication.objects.create(
            name="Drop Partner",
            client_id="drop_partner_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://posthog.com/api/wizard/oauth-callback",
            algorithm="RS256",
            provisioning_auth_method="hmac",
            provisioning_signing_secret=HMAC_SECRET,
            provisioning_partner_type="posthog_website",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
        )

    def _create_grant_via_api(self):
        with (
            patch(
                "ee.api.agentic_provisioning.views.GitHubIntegration.github_user_from_code",
                return_value=AUTHORIZATION,
            ),
            patch("ee.api.agentic_provisioning.github_grants.github_request", return_value=EMAILS_RESPONSE),
        ):
            return self._post_signed(
                "/api/agentic/provisioning/github/grants",
                {"code": "gh_code", "redirect_uri": "https://posthog.com/api/wizard/github/callback"},
            )

    def test_create_grant_happy_path(self):
        with (
            patch(
                "ee.api.agentic_provisioning.views.GitHubIntegration.github_user_from_code",
                return_value=AUTHORIZATION,
            ) as mock_exchange,
            patch("ee.api.agentic_provisioning.github_grants.github_request", return_value=EMAILS_RESPONSE),
        ):
            response = self._post_signed(
                "/api/agentic/provisioning/github/grants",
                {"code": "gh_code", "redirect_uri": "https://posthog.com/api/wizard/github/callback"},
            )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["gh_login"] == "octocat"
        assert body["email"] == "octocat@example.com"
        assert body["grant_id"]
        # The redirect_uri must flow into the exchange — GitHub rejects mismatches.
        mock_exchange.assert_called_once_with("gh_code", redirect_uri="https://posthog.com/api/wizard/github/callback")

        # Tokens are encrypted at rest in the cache; the loaded grant round-trips them.
        raw = cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{body['grant_id']}")
        assert isinstance(raw, str)
        assert ACCESS_TOKEN not in raw
        grant = github_grants.load_grant(body["grant_id"], self.partner)
        assert grant is not None
        assert grant.access_token == ACCESS_TOKEN
        assert grant.email == "octocat@example.com"

    @parameterized.expand(
        [
            ("missing_code", {}, 400, "invalid_request"),
            ("blank_code", {"code": ""}, 400, "invalid_request"),
        ]
    )
    def test_create_grant_requires_code(self, _name, body, expected_status, expected_code):
        response = self._post_signed("/api/agentic/provisioning/github/grants", body)
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == expected_code

    def test_create_grant_exchange_failure_returns_502(self):
        with patch(
            "ee.api.agentic_provisioning.views.GitHubIntegration.github_user_from_code",
            return_value=None,
        ):
            response = self._post_signed("/api/agentic/provisioning/github/grants", {"code": "bad_code"})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "github_exchange_failed"

    def test_create_grant_without_verified_email_returns_null_email(self):
        no_verified = _github_response(200, [{"email": "a@example.com", "primary": True, "verified": False}])
        with (
            patch(
                "ee.api.agentic_provisioning.views.GitHubIntegration.github_user_from_code",
                return_value=AUTHORIZATION,
            ),
            patch("ee.api.agentic_provisioning.github_grants.github_request", return_value=no_verified),
        ):
            response = self._post_signed("/api/agentic/provisioning/github/grants", {"code": "gh_code"})
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["email"] is None
        grant = github_grants.load_grant(body["grant_id"], self.partner)
        assert grant is not None
        assert grant.email is None

    def test_create_grant_email_access_denied_returns_502(self):
        denied = _github_response(404, {"message": "Not Found"})
        with (
            patch(
                "ee.api.agentic_provisioning.views.GitHubIntegration.github_user_from_code",
                return_value=AUTHORIZATION,
            ),
            patch("ee.api.agentic_provisioning.github_grants.github_request", return_value=denied),
        ):
            response = self._post_signed("/api/agentic/provisioning/github/grants", {"code": "gh_code"})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "email_unavailable"

    def test_create_grant_requires_partner_auth(self):
        response = self.client.post(
            "/api/agentic/provisioning/github/grants",
            data={"code": "gh_code"},
            format="json",
            HTTP_API_VERSION="0.1d",
        )
        assert response.status_code == 401

    def test_create_grant_requires_account_creation_permission(self):
        self.partner.provisioning_can_create_accounts = False
        self.partner.save()
        response = self._post_signed("/api/agentic/provisioning/github/grants", {"code": "gh_code"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    def test_create_grant_partner_rate_limited(self):
        self.partner.provisioning_rate_limit_github_grants = 1
        self.partner.save()
        first = self._create_grant_via_api()
        assert first.status_code == 200
        second = self._create_grant_via_api()
        assert second.status_code == 429
        assert second["Retry-After"]

    @parameterized.expand(
        [
            ("agentic_tree", "/api/agentic/provisioning/github/grants"),
            ("alias_tree", "/api/provisioning/github/grants"),
        ]
    )
    def test_repositories_happy_path(self, _name, base_url):
        grant = github_grants.create_grant(self.partner, AUTHORIZATION, "octocat@example.com")

        def fake_github_request(method, url, **kwargs):
            if url.endswith("/user/installations"):
                return INSTALLATIONS_RESPONSE
            return REPOSITORIES_RESPONSE

        with patch("ee.api.agentic_provisioning.github_grants.github_request", side_effect=fake_github_request):
            response = self._get_signed(f"{base_url}/{grant.grant_id}/repositories")

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["gh_login"] == "octocat"
        assert body["installations"] == [{"id": "777", "account_login": "octocat", "repository_selection": "selected"}]
        assert body["repositories"] == [
            {
                "installation_id": "777",
                "full_name": "octocat/hello-world",
                "default_branch": "main",
                "private": False,
            }
        ]

    def test_repositories_unknown_grant_returns_404(self):
        response = self._get_signed("/api/agentic/provisioning/github/grants/nonexistent/repositories")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grant_not_found"

    def test_repositories_grant_of_other_partner_returns_404(self):
        other_partner = OAuthApplication.objects.create(
            name="Other Partner",
            client_id="other_partner_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://other.example.com",
            algorithm="RS256",
            provisioning_auth_method="bearer",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
        )
        grant = github_grants.create_grant(other_partner, AUTHORIZATION, "octocat@example.com")
        response = self._get_signed(f"/api/agentic/provisioning/github/grants/{grant.grant_id}/repositories")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grant_not_found"

    def test_repositories_poll_rate_limited(self):
        grant = github_grants.create_grant(self.partner, AUTHORIZATION, "octocat@example.com")
        url = f"/api/agentic/provisioning/github/grants/{grant.grant_id}/repositories"

        def fake_github_request(method, request_url, **kwargs):
            if request_url.endswith("/user/installations"):
                return INSTALLATIONS_RESPONSE
            return REPOSITORIES_RESPONSE

        with (
            patch("ee.api.agentic_provisioning.views.GITHUB_GRANT_POLL_RATE_LIMIT_MAX", 1),
            patch("ee.api.agentic_provisioning.github_grants.github_request", side_effect=fake_github_request),
        ):
            first = self._get_signed(url)
            second = self._get_signed(url)
        assert first.status_code == 200
        assert second.status_code == 429
        assert second["Retry-After"]

    def test_repositories_github_failure_returns_502(self):
        grant = github_grants.create_grant(self.partner, AUTHORIZATION, "octocat@example.com")
        with patch(
            "ee.api.agentic_provisioning.github_grants.github_request",
            return_value=_github_response(500, {}),
        ):
            response = self._get_signed(f"/api/agentic/provisioning/github/grants/{grant.grant_id}/repositories")
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "github_unavailable"
