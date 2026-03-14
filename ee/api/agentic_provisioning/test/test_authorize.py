import json
import time
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.test import override_settings
from django.utils import timezone

from posthog.models.user import User

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET
from ee.models.agentic_provisioning import AgenticProvisioningState

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
        AgenticProvisioningState.objects.create(
            purpose=AgenticProvisioningState.Purpose.PENDING_AUTH,
            token=state,
            payload=data,
            expires_at=timezone.now() + timedelta(seconds=600),
        )

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
        assert not AgenticProvisioningState.objects.filter(
            token="state_once",
            purpose=AgenticProvisioningState.Purpose.PENDING_AUTH,
        ).exists()

    def test_auth_code_created_in_db(self):
        self._set_pending_auth("state_code", self.user.email)
        res = self.client.get("/api/agentic/authorize?state=state_code")
        code = res["Location"].split("code=")[1].split("&")[0]
        state = AgenticProvisioningState.objects.get(
            token=code,
            purpose=AgenticProvisioningState.Purpose.AUTH_CODE,
        )
        assert state.payload["user_id"] == self.user.id
        assert state.payload["org_id"] == str(self.team.organization.id)
        assert state.payload["team_id"] == self.team.id
        assert state.payload["scopes"] == ["query:read", "project:read"]

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
        )
        assert token_res.status_code == 200
        data = token_res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"


@override_settings(STRIPE_ORCHESTRATOR_CALLBACK_URL=DUMMY_CALLBACK)
class TestAgenticAuthorizeNoOrg(APIBaseTest):
    def test_user_without_org_redirects_with_error(self):
        orphan = User.objects.create(email="orphan@example.com", first_name="Orphan")
        self.client.force_login(orphan)
        AgenticProvisioningState.objects.create(
            purpose=AgenticProvisioningState.Purpose.PENDING_AUTH,
            token="state_no_org",
            payload={"email": "orphan@example.com", "scopes": [], "stripe_account_id": "", "region": "US"},
            expires_at=timezone.now() + timedelta(seconds=600),
        )
        res = self.client.get("/api/agentic/authorize?state=state_no_org")
        assert res.status_code == 302
        assert "error=no_organization" in res["Location"]
