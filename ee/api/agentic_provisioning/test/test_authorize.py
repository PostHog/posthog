import json
import time

import pytest
from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.user import User

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET

DUMMY_CALLBACK = "https://marketplace.stripe.com/oauth/callback"


@override_settings(STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
class TestAgenticAuthorize(APIBaseTest):
    def _set_pending_auth(self, state: str, email: str, **extra):
        data = {
            "email": email,
            "scopes": ["query:read", "project:read"],
            "stripe_account_id": "acct_123",
            "region": "US",
            **extra,
        }
        cache.set(f"{PENDING_AUTH_CACHE_PREFIX}{state}", data, timeout=600)

    def test_requires_login(self):
        self.client.logout()
        res = self.client.get("/api/agentic/authorize?state=test_state")
        assert res.status_code == 302
        assert "/login" in res["Location"]

    def test_expired_state_redirects_with_error(self):
        res = self.client.get("/api/agentic/authorize?state=nonexistent")
        assert res.status_code == 302
        assert "error=expired_or_invalid_state" in res["Location"]

    def test_missing_state_redirects_with_error(self):
        res = self.client.get("/api/agentic/authorize")
        assert res.status_code == 302
        assert "error=missing_state" in res["Location"]

    def test_email_mismatch_redirects_with_error(self):
        self._set_pending_auth("state_mismatch", "other@example.com")
        res = self.client.get("/api/agentic/authorize?state=state_mismatch")
        assert res.status_code == 302
        assert "error=email_mismatch" in res["Location"]

    def test_redirects_to_callback_with_code(self):
        self._set_pending_auth("state_ok", self.user.email)
        res = self.client.get("/api/agentic/authorize?state=state_ok")
        assert res.status_code == 302
        assert res["Location"].startswith(DUMMY_CALLBACK)
        assert "code=" in res["Location"]
        assert "state=state_ok" in res["Location"]

    def test_pending_auth_deleted_after_use(self):
        self._set_pending_auth("state_once", self.user.email)
        self.client.get("/api/agentic/authorize?state=state_once")
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_once") is None

    def test_auth_code_created_in_cache(self):
        self._set_pending_auth("state_code", self.user.email)
        res = self.client.get("/api/agentic/authorize?state=state_code")
        code = res["Location"].split("code=")[1].split("&")[0]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        assert code_data["user_id"] == self.user.id
        assert code_data["org_id"] == str(self.team.organization.id)
        assert code_data["team_id"] == self.team.id
        assert code_data["scopes"] == ["query:read", "project:read"]

    @pytest.mark.requires_secrets
    @override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET, STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
    def test_full_a1_flow_with_token_exchange(self):
        self._set_pending_auth("state_e2e", self.user.email)

        res = self.client.get("/api/agentic/authorize?state=state_e2e")
        assert res.status_code == 302
        code = res["Location"].split("code=")[1].split("&")[0]

        body = json.dumps({"grant_type": "authorization_code", "code": code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        token_res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert token_res.status_code == 200
        data = token_res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"


class AgenticAuthorizeMultiOrgBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.org2 = Organization.objects.create(name="Second Org")
        OrganizationMembership.objects.create(user=self.user, organization=self.org2, level=15)
        self.team2 = Team.objects.create(organization=self.org2, name="Second Project", api_token="token_2")

    def _set_pending_auth(self, state: str, email: str, **extra):
        data = {
            "email": email,
            "scopes": ["query:read", "project:read"],
            "stripe_account_id": "acct_123",
            "region": "US",
            **extra,
        }
        cache.set(f"{PENDING_AUTH_CACHE_PREFIX}{state}", data, timeout=600)


@override_settings(STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
class TestAgenticAuthorizeMultiOrg(AgenticAuthorizeMultiOrgBase):
    def test_multi_org_redirects_to_spa(self):
        self._set_pending_auth("state_multi", self.user.email)
        res = self.client.get("/api/agentic/authorize?state=state_multi&scope=query:read+project:read")
        assert res.status_code == 302
        assert "/agentic/authorize?" in res["Location"]
        assert "state=state_multi" in res["Location"]

    def test_multi_org_does_not_consume_state(self):
        self._set_pending_auth("state_preserve", self.user.email)
        self.client.get("/api/agentic/authorize?state=state_preserve")
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_preserve") is not None


@override_settings(STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
class TestAgenticAuthorizeConfirm(AgenticAuthorizeMultiOrgBase):
    def test_confirm_creates_auth_code_for_selected_team(self):
        self._set_pending_auth("state_confirm", self.user.email)
        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "state_confirm", "team_id": self.team2.id},
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.json()
        assert data["redirect_url"].startswith(DUMMY_CALLBACK)
        assert "code=" in data["redirect_url"]
        assert "state=state_confirm" in data["redirect_url"]

        code = data["redirect_url"].split("code=")[1].split("&")[0]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data["team_id"] == self.team2.id
        assert code_data["org_id"] == str(self.org2.id)

    def test_confirm_consumes_pending_state(self):
        self._set_pending_auth("state_consume", self.user.email)
        self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "state_consume", "team_id": self.team.id},
            content_type="application/json",
        )
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_consume") is None

    def test_confirm_rejects_expired_state(self):
        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "nonexistent", "team_id": self.team.id},
            content_type="application/json",
        )
        assert res.status_code == 400
        assert res.json()["error"] == "expired_or_invalid_state"

    def test_confirm_rejects_email_mismatch(self):
        self._set_pending_auth("state_wrong_email", "other@example.com")
        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "state_wrong_email", "team_id": self.team.id},
            content_type="application/json",
        )
        assert res.status_code == 403
        assert res.json()["error"] == "email_mismatch"

    def test_confirm_rejects_inaccessible_team(self):
        self._set_pending_auth("state_no_access", self.user.email)
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Project", api_token="token_other")

        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "state_no_access", "team_id": other_team.id},
            content_type="application/json",
        )
        assert res.status_code == 403
        assert res.json()["error"] == "team_not_accessible"

    def test_confirm_rejects_nonexistent_team(self):
        self._set_pending_auth("state_bad_team", self.user.email)
        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "state_bad_team", "team_id": 999999},
            content_type="application/json",
        )
        assert res.status_code == 404
        assert res.json()["error"] == "team_not_found"

    def test_confirm_rejects_missing_params(self):
        res = self.client.post(
            "/api/agentic/authorize/confirm/",
            {"state": "something"},
            content_type="application/json",
        )
        assert res.status_code == 400


@override_settings(STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
class TestAgenticAuthorizeNoOrg(APIBaseTest):
    def test_user_without_org_redirects_with_error(self):
        orphan = User.objects.create(email="orphan@example.com", first_name="Orphan")
        self.client.force_login(orphan)
        cache.set(
            f"{PENDING_AUTH_CACHE_PREFIX}state_no_org",
            {"email": "orphan@example.com", "scopes": [], "stripe_account_id": "", "region": "US"},
            timeout=600,
        )
        res = self.client.get("/api/agentic/authorize?state=state_no_org")
        assert res.status_code == 302
        assert "error=no_organization" in res["Location"]
