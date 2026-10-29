import json
import time
import uuid
import base64
import hashlib
import secrets
import dataclasses
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from posthog.api.oauth.client_assertion import (
    AGENTIC_TOKEN_ENDPOINT_PATH,
    CLIENT_ASSERTION_TYPE_JWT_BEARER,
    expected_assertion_audiences,
)
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.access_control.backend.models.access_control import AccessControl

from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

    from posthog.models.oauth import OAuthApplication

TEST_PARTNER_CLIENT_ID = "test_partner_client_id"
# Stored hashed by ClientSecretField.pre_save, so the plaintext has to live here for
# requests to present it.
TEST_PARTNER_CLIENT_SECRET = "test_partner_client_secret"

# The test partner can create accounts, so it has to sign its requests with a private key.
TEST_PARTNER_JWKS_URI = "https://partner.example.com/.well-known/jwks.json"
TEST_PARTNER_KID = "test-partner-key"
# Generated once at import: RSA keygen is slow, and no test mutates the key.
TEST_PARTNER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PARTNER_JWKS = {
    "keys": [
        {
            **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(TEST_PARTNER_KEY.public_key())),
            "kid": TEST_PARTNER_KID,
            "use": "sig",
            "alg": "RS256",
        }
    ]
}

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


# A partner granted everything, so a test narrows to the one capability it is about rather
# than restating the rest. `provisioning_config(can_issue_deep_links=False)` reads as the
# thing under test; a literal dict at each call site does not.
TEST_PARTNER_PROVISIONING: dict[str, bool] = {
    "active": True,
    "can_create_accounts": True,
    "can_provision_resources": True,
    "can_issue_deep_links": True,
    # Stands in for the one grandfathered app that still mints a provisioned PAT.
    "issues_personal_api_key": True,
}


def provisioning_config(**overrides) -> dict:
    """The stored form of the test partner's config. Goes into ``_provisioning_config``."""
    from posthog.models.oauth_provisioning import ProvisioningConfig

    return ProvisioningConfig(**{**TEST_PARTNER_PROVISIONING, **overrides}).model_dump(mode="json")


def patched_budget(view_cls, method: str, endpoint: str, budget, *, multipliers=None):
    """Shrink a handler's declared bucket budget for a test.

    The declaration lives on the handler function, so tests patch it there
    rather than replaying dozens of requests to exhaust a real budget. Pass
    ``multipliers`` (e.g. FLAT_MULTIPLIERS) when the test partner's tier would
    otherwise scale the patched budget back up.
    """
    budgets = getattr(view_cls, method)._provisioning_budgets
    changes: dict = {"budget": budget}
    if multipliers is not None:
        changes["multipliers"] = multipliers
    return patch.dict(budgets, {endpoint: dataclasses.replace(budgets[endpoint], **changes)})


class ProvisioningTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        jwks_fetch = patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(TEST_PARTNER_JWKS, None)
        )
        jwks_fetch.start()
        self.addCleanup(jwks_fetch.stop)
        self.partner = self._ensure_partner_app()

    def _ensure_partner_app(self):
        from posthog.models.oauth import OAuthApplication

        app, _ = OAuthApplication.objects.get_or_create(
            client_id=TEST_PARTNER_CLIENT_ID,
            defaults={
                "name": "Test Provisioning Partner",
                "client_secret": "",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "jwks_uri": TEST_PARTNER_JWKS_URI,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://partner.example.com/callback",
                "algorithm": "RS256",
                "scopes": TEST_PARTNER_SCOPES,
                "is_provisioning_partner": True,
                "_provisioning_config": provisioning_config(),
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

    def _client_assertion(self, partner=None) -> str:
        partner = partner or self.partner
        now = int(time.time())
        claims = {
            "iss": partner.client_id,
            "sub": partner.client_id,
            "aud": expected_assertion_audiences(AGENTIC_TOKEN_ENDPOINT_PATH)[0],
            # Each assertion is single use, so every request needs its own jti.
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 60,
        }
        return jwt.encode(claims, TEST_PARTNER_KEY, algorithm="RS256", headers={"kid": TEST_PARTNER_KID})

    def _client_auth(self, partner=None, secret: str | None = None) -> dict[str, str]:
        """The body fields that authenticate the partner: a signed assertion for a private_key_jwt
        partner, and the client_secret_post form for a partner registered with a secret."""
        partner = partner or self.partner
        if partner.uses_private_key_jwt_auth:
            return {
                "client_id": partner.client_id,
                "client_assertion": self._client_assertion(partner),
                "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
            }
        return {
            "client_id": partner.client_id,
            "client_secret": TEST_PARTNER_CLIENT_SECRET if secret is None else secret,
        }

    def _basic_auth_header(self, partner=None, secret: str | None = None) -> str:
        """The client_secret_basic form, which is the only one a GET can carry."""
        partner = partner or self.partner
        raw = f"{quote_plus(partner.client_id)}:{quote_plus(TEST_PARTNER_CLIENT_SECRET if secret is None else secret)}"
        return f"Basic {base64.b64encode(raw.encode()).decode()}"

    def _post_as_partner(self, url: str, data: dict | None = None, partner=None, **kwargs):
        return self._post_api(url, {**(data or {}), **self._client_auth(partner)}, **kwargs)

    def _pkce_pair(self) -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
        return verifier, challenge

    def _mint_auth_code(
        self, scopes: list[str] | None = None, partner: "OAuthApplication | None" = None, team_id: int | None = None
    ) -> tuple[str, str]:
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
                "team_id": team_id if team_id is not None else self.team.id,
                "partner_id": str(partner.id),
                "scopes": scopes if scopes is not None else ["query:read"],
                "region": "US",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            timeout=300,
        )
        return code, verifier

    def _request_bearer_token(
        self,
        scopes: list[str] | None = None,
        partner: "OAuthApplication | None" = None,
        secret: str | None = None,
        team_id: int | None = None,
    ) -> "_MonkeyPatchedResponse":
        partner = partner or self.partner
        code, verifier = self._mint_auth_code(scopes=scopes, partner=partner, team_id=team_id)
        data = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier}
        # A confidential partner has to authenticate at the token endpoint; a public one
        # exchanges on the code_verifier alone.
        if partner.requires_client_authentication:
            data.update(self._client_auth(partner, secret=secret))
        return self.client.post("/api/agentic/oauth/token", data=data)

    def _get_bearer_token(self) -> str:
        return self._request_bearer_token().json()["access_token"]

    def _restrict_team_access(self, team: Team) -> None:
        """Make ``self.user`` an org member who is denied access to ``team``."""
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=team,
            access_level="none",
            resource="project",
            resource_id=str(team.id),
        )
