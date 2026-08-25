import json
import base64
import hashlib
import secrets
import dataclasses
from urllib.parse import quote_plus

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX
from ee.models.rbac.access_control import AccessControl

TEST_PARTNER_CLIENT_ID = "test_partner_client_id"
# Stored hashed by ClientSecretField.pre_save, so the plaintext has to live here for
# requests to present it.
TEST_PARTNER_CLIENT_SECRET = "test_partner_client_secret"

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
# than restating the other eight. `provisioning_config(can_start_wizard_runs=False)` reads as
# the thing under test; a literal dict at each call site does not.
TEST_PARTNER_PROVISIONING: dict[str, bool] = {
    "active": True,
    "can_create_accounts": True,
    "can_provision_resources": True,
    "can_use_github_grants": True,
    "can_start_wizard_runs": True,
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
        self.partner = self._ensure_partner_app()

    def _ensure_partner_app(self):
        from posthog.models.oauth import OAuthApplication

        app, _ = OAuthApplication.objects.get_or_create(
            client_id=TEST_PARTNER_CLIENT_ID,
            defaults={
                "name": "Test Provisioning Partner",
                "client_secret": TEST_PARTNER_CLIENT_SECRET,
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
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

    def _client_credentials(self, partner=None, secret: str | None = None) -> dict[str, str]:
        """The client_secret_post form: credentials merged into the request body."""
        partner = partner or self.partner
        return {
            "client_id": partner.client_id,
            "client_secret": TEST_PARTNER_CLIENT_SECRET if secret is None else secret,
        }

    def _basic_auth_header(self, partner=None, secret: str | None = None) -> str:
        """The client_secret_basic form, which is the only one a GET can carry."""
        partner = partner or self.partner
        raw = f"{quote_plus(partner.client_id)}:{quote_plus(TEST_PARTNER_CLIENT_SECRET if secret is None else secret)}"
        return f"Basic {base64.b64encode(raw.encode()).decode()}"

    def _post_with_client_secret(self, url: str, data: dict | None = None, partner=None, **kwargs):
        return self._post_api(url, {**(data or {}), **self._client_credentials(partner)}, **kwargs)

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

    def _request_bearer_token(self, scopes: list[str] | None = None, partner=None, secret: str | None = None):
        partner = partner or self.partner
        code, verifier = self._mint_auth_code(scopes=scopes, partner=partner)
        data = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier}
        # A confidential partner has to authenticate at the token endpoint; a public one
        # exchanges on the code_verifier alone.
        if partner.uses_client_secret_auth:
            data.update(self._client_credentials(partner, secret=secret))
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
