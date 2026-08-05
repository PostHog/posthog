import time
import base64
import hashlib
import secrets
from urllib.parse import urlencode

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_oauth_refresh_token

from ee.models.rbac.access_control import AccessControl
from ee.partners.stripe.api.provisioning.signature import compute_signature
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, HMAC_SECRET, StripeProvisioningTestBase

TOKEN_URL = f"{BASE_PATH}/oauth/token"


class TestOAuthToken(StripeProvisioningTestBase):
    def _post_token(self, params: dict, signed: bool = True):
        body = urlencode(params).encode()
        headers = {"api-version": "0.1d"}
        if signed:
            ts = int(time.time())
            headers["stripe-signature"] = f"t={ts},v1={compute_signature(HMAC_SECRET, ts, body)}"
        return self.client.post(TOKEN_URL, data=body, content_type="application/x-www-form-urlencoded", headers=headers)

    def test_authorization_code_exchange(self):
        self._seed_auth_code("code_happy")
        res = self._post_token({"grant_type": "authorization_code", "code": "code_happy"})
        assert res.status_code == 200
        data = res.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["expires_in"] == 365 * 24 * 3600
        assert data["account"]["id"] == str(self.organization.id)
        assert data["account"]["payment_credentials"] == "orchestrator"
        assert any(team["id"] == self.team.id for team in data["account"]["available_teams"])

    def test_auth_code_is_single_use(self):
        self._seed_auth_code("code_once")
        assert self._post_token({"grant_type": "authorization_code", "code": "code_once"}).status_code == 200
        res = self._post_token({"grant_type": "authorization_code", "code": "code_once"})
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def test_pkce_code_redeemable_with_verifier_and_no_signature(self):
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
        self._seed_auth_code("code_pkce", code_challenge=challenge, code_challenge_method="S256")
        res = self._post_token(
            {"grant_type": "authorization_code", "code": "code_pkce", "code_verifier": verifier}, signed=False
        )
        assert res.status_code == 200
        assert res.json()["access_token"].startswith("pha_")

    @parameterized.expand(
        [
            ("unsupported_grant", {"grant_type": "password"}, True, 400, "unsupported_grant_type"),
            ("missing_code", {"grant_type": "authorization_code"}, True, 400, "invalid_request"),
            ("unknown_code", {"grant_type": "authorization_code", "code": "nope"}, True, 400, "invalid_grant"),
            ("missing_refresh_token", {"grant_type": "refresh_token"}, True, 400, "invalid_request"),
            (
                "unknown_refresh_token",
                {"grant_type": "refresh_token", "refresh_token": "phr_x"},
                True,
                400,
                "invalid_grant",
            ),
        ]
    )
    def test_rejected_grants(self, _name, params, signed, status, error):
        res = self._post_token(params, signed=signed)
        assert res.status_code == status
        assert res.json()["error"] == error

    def test_unsigned_non_pkce_code_requires_authentication(self):
        self._seed_auth_code("code_unsigned")
        res = self._post_token({"grant_type": "authorization_code", "code": "code_unsigned"}, signed=False)
        assert res.status_code == 401
        assert res.json() == {"error": "invalid_request", "error_description": "Authentication required"}

    def test_pkce_code_requires_verifier(self):
        self._seed_auth_code("code_pkce_only", code_challenge="a" * 43, code_challenge_method="S256")
        res = self._post_token({"grant_type": "authorization_code", "code": "code_pkce_only"}, signed=False)
        assert res.status_code == 401
        assert res.json()["error_description"] == "code_verifier is required for PKCE"

    def test_requested_scopes_are_granted_without_ceiling(self):
        # No scope ceiling in this namespace: whatever the code requests is granted.
        self._seed_auth_code("code_wide", scopes=["query:read", "project:read"])
        res = self._post_token({"grant_type": "authorization_code", "code": "code_wide"})
        assert res.status_code == 200
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert set(token.scope.split()) == {"query:read", "project:read"}

    def test_sessions_revoked_fails_closed_for_codes_without_issued_at(self):
        self.stripe_app.sessions_revoked_at = timezone.now()
        self.stripe_app.save(update_fields=["sessions_revoked_at"])
        self._seed_auth_code("code_revoked")
        res = self._post_token({"grant_type": "authorization_code", "code": "code_revoked"})
        assert res.status_code == 400
        assert res.json() == {
            "error": "invalid_grant",
            "error_description": "Application sessions were revoked; re-authorize.",
        }

    def test_refresh_token_rotation(self):
        first = self._request_bearer_token().json()
        res = self._post_token({"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        assert res.status_code == 200
        rotated = res.json()
        assert rotated["access_token"] != first["access_token"]
        assert rotated["refresh_token"] != first["refresh_token"]
        assert rotated["access_token"].startswith("pha_")

        # The rotated-out refresh token is revoked, and the old access token is gone.
        replay = self._post_token({"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"
        detail = self._get_signed_with_bearer(
            f"{BASE_PATH}/provisioning/resources/{self.team.id}", token=first["access_token"]
        )
        assert detail.status_code == 401

    def test_available_teams_exclude_acl_restricted_teams(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user, organization=self.organization, name="Restricted team"
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        data = self._request_bearer_token().json()
        team_ids = [team["id"] for team in data["account"]["available_teams"]]
        assert self.team.id in team_ids
        assert restricted_team.id not in team_ids

    def test_code_bound_to_non_stripe_app_not_redeemable(self):
        other_app = self._create_other_partner_app()
        self._seed_auth_code("code_other_partner", partner_id=str(other_app.id))

        res = self._post_token({"grant_type": "authorization_code", "code": "code_other_partner"})
        assert res.status_code == 400
        assert res.json() == {
            "error": "invalid_grant",
            "error_description": "Authorization code was not issued for the Stripe Projects app",
        }

    def test_refresh_token_from_non_stripe_app_not_rotatable(self):
        other_app = self._create_other_partner_app()
        refresh_value = generate_random_oauth_refresh_token(None)
        OAuthRefreshToken.objects.create(
            application=other_app, token=refresh_value, user=self.user, scoped_teams=[self.team.id]
        )

        res = self._post_token({"grant_type": "refresh_token", "refresh_token": refresh_value})
        assert res.status_code == 400
        assert res.json() == {
            "error": "invalid_grant",
            "error_description": "Refresh token was not issued for the Stripe Projects app",
        }
        # Rejected before any mutation: the token survives unrevoked.
        assert OAuthRefreshToken.objects.get(token=refresh_value).revoked is None

    def test_refresh_is_possession_only(self):
        first = self._request_bearer_token().json()
        res = self._post_token({"grant_type": "refresh_token", "refresh_token": first["refresh_token"]}, signed=False)
        assert res.status_code == 200
