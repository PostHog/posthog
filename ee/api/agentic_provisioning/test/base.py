import json
import base64
import hashlib
import secrets

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APIClient

from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX

TEST_PARTNER_CLIENT_ID = "test_partner_client_id"

# Broad ceiling so token exchanges in tests aren't rejected by the per-app scope cap.
TEST_PARTNER_SCOPES = [
    "query:read",
    "feature_flag:read",
    "insight:read",
    "organization:read",
    "person:read",
    "project:read",
    "user:read",
]


class ProvisioningTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.partner = self._ensure_partner_app()

    def _ensure_partner_app(self):
        from posthog.models.oauth import OAuthApplication

        app, _ = OAuthApplication.objects.get_or_create(
            client_id=TEST_PARTNER_CLIENT_ID,
            defaults={
                "name": "Test Provisioning Partner",
                "client_secret": "",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://partner.example.com/callback",
                "algorithm": "RS256",
                "scopes": TEST_PARTNER_SCOPES,
                "provisioning_auth_method": "bearer",
                "provisioning_partner_type": "test_partner",
                "provisioning_active": True,
                "provisioning_can_create_accounts": True,
                "provisioning_can_provision_resources": True,
                "provisioning_can_issue_deep_links": True,
                # Stands in for the one grandfathered app that still mints a provisioned PAT.
                "provisioning_issues_personal_api_key": True,
            },
        )
        return app

    def _post_api(self, url: str, data: dict | bytes | None = None, content_type: str = "application/json", **kwargs):
        body: bytes
        if content_type == "application/json":
            body = json.dumps(data or {}).encode()
        elif isinstance(data, bytes):
            body = data
        else:
            body = b""
        return self.client.post(
            url,
            data=body,
            content_type=content_type,
            **kwargs,
        )

    def _get_api(self, url: str, **kwargs):
        return self.client.get(url, **kwargs)

    def _get_with_bearer(self, url: str, token: str, **kwargs):
        return self._get_api(url, HTTP_AUTHORIZATION=f"Bearer {token}", **kwargs)

    def _post_with_bearer(self, url: str, data: dict | None = None, token: str = "", **kwargs):
        return self._post_api(url, data, HTTP_AUTHORIZATION=f"Bearer {token}", **kwargs)

    def _pkce_pair(self) -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
        return verifier, challenge

    def _mint_auth_code(self, scopes: list[str] | None = None, partner=None) -> tuple[str, str]:
        """Seed an auth code in the cache for the test partner. Returns (code, code_verifier)."""
        partner = partner or self.partner
        verifier, challenge = self._pkce_pair()
        code = secrets.token_urlsafe(16)
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "issued_at": timezone.now().isoformat(),
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "partner_id": str(partner.id),
                "scopes": scopes if scopes is not None else ["query:read"],
                "region": "US",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            timeout=300,
        )
        return code, verifier

    def _request_bearer_token(self, scopes: list[str] | None = None, partner=None):
        code, verifier = self._mint_auth_code(scopes=scopes, partner=partner)
        return self.client.post(
            "/api/agentic/oauth/token",
            data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        )

    def _get_bearer_token(self) -> str:
        return self._request_bearer_token().json()["access_token"]
