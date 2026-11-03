import json
import time
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

import jwt
from oauth2_provider.utils import jwk_from_pem
from parameterized import parameterized
from rest_framework import status

from posthog.api.oauth.cimd import CIMDFetchError
from posthog.auth import WorkloadAccessTokenAuthentication
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.models.workload_trust_policy import WorkloadTrustPolicy, WorkloadTrustPolicyRequest
from posthog.settings.utils import generate_rsa_private_key_pem
from posthog.test.authentication_checks import covers_authentication
from posthog.workload_identity.test.fixtures import FAKE_WORKLOAD_ISSUER, with_fake_workload_provider
from posthog.workload_identity.token_exchange import TOKEN_EXCHANGE_GRANT_TYPE

from products.annotations.backend.models import Annotation
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

# RSA key generation is slow, so the keys are made once per module.
_PROVIDER_KEY_PEM = generate_rsa_private_key_pem()
_OTHER_KEY_PEM = generate_rsa_private_key_pem()
_POSTHOG_KEY_PEM = generate_rsa_private_key_pem()
_PROVIDER_KEY_ID = "ci-key-1"
_SITE_URL = "https://posthog.test"


def _jwks() -> dict[str, Any]:
    public_jwk = json.loads(jwk_from_pem(_PROVIDER_KEY_PEM).export_public())
    return {"keys": [{**public_jwk, "kid": _PROVIDER_KEY_ID, "alg": "RS256", "use": "sig"}]}


def _oidc_token(*, signing_key: str = _PROVIDER_KEY_PEM, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": FAKE_WORKLOAD_ISSUER,
        "aud": _SITE_URL,
        "iat": now,
        "exp": now + 300,
        "repository": "acme/web",
        "repository_id": "1234",
        "ref": "refs/heads/main",
        "environment": "production",
        "workflow": "deploy.yml",
        "run_id": "987",
        "sha": "abc123",
        **overrides,
    }
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": _PROVIDER_KEY_ID})


@with_fake_workload_provider()
@override_settings(SITE_URL=_SITE_URL, OIDC_RSA_PRIVATE_KEY=_POSTHOG_KEY_PEM)
class TestWorkloadTokenExchange(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        jwks_patcher = patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(_jwks(), None)
        )
        jwks_patcher.start()
        self.addCleanup(jwks_patcher.stop)
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.policy = self._create_policy()

    def _create_policy(self, team: Team | None = None, **overrides: Any) -> WorkloadTrustPolicy:
        target = team or self.team
        fields: dict[str, Any] = {
            "name": "Production deploys",
            "issuer": FAKE_WORKLOAD_ISSUER,
            "subject_name": "acme/web",
            "subject": "1234",
            "conditions": {"ref": "refs/heads/main"},
            "scopes": ["annotation:write"],
            **overrides,
        }
        return WorkloadTrustPolicy.objects.for_team(target.id).create(team=target, **fields)

    def _exchange(self, subject_token: str | None = None, **overrides: str) -> Any:
        self.client.logout()
        data = {
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "subject_token": subject_token or _oidc_token(),
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "resource": f"{_SITE_URL}/api/projects/{self.team.id}",
            **overrides,
        }
        return self.client.post("/oauth/token/", data)

    def _access_token(self) -> str:
        response = self._exchange()
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["access_token"]

    def _call(self, method: str, path: str, token: str, data: dict[str, Any] | None = None) -> Any:
        self.client.logout()
        return getattr(self.client, method)(path, data or {}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")

    @covers_authentication(WorkloadAccessTokenAuthentication)
    def test_token_acts_as_the_oldest_owner_with_the_policy_ceiling(self) -> None:
        newer_owner = User.objects.create_and_join(
            self.organization, "newer-owner@example.com", None, level=OrganizationMembership.Level.OWNER
        )

        response = self._exchange()
        body = response.json()
        created = self._call(
            "post",
            f"/api/projects/{self.team.id}/annotations/",
            body["access_token"],
            {"content": "Deployed", "date_marker": "2026-01-01T00:00:00Z", "scope": "project"},
        )

        assert response.status_code == status.HTTP_200_OK, body
        assert (response["Cache-Control"], response["Pragma"]) == ("no-store", "no-cache")
        assert body["token_type"] == "Bearer"
        assert body["issued_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
        assert body["scope"] == "annotation:write"
        assert 0 < body["expires_in"] <= 600
        assert "refresh_token" not in body
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        annotation = Annotation.objects.get(pk=created.json()["id"], team_id=self.team.id)
        assert annotation.created_by_id == self.user.id != newer_owner.id
        entry = ActivityLog.objects.filter(scope="Annotation", item_id=str(annotation.pk)).get()
        assert (entry.credential_type, entry.credential_id) == ("oidc_workload", str(self.policy.pk))

    @parameterized.expand(
        [
            ("unknown_issuer", {"iss": "https://token.ci.example.org"}, {}, "workload_issuer_not_allowed"),
            ("wrong_audience", {"aud": "https://other.example.com"}, {}, "workload_token_invalid"),
            ("expired", {"exp": int(time.time()) - 120, "iat": int(time.time()) - 600}, {}, "workload_token_invalid"),
            ("recreated_repository", {"repository_id": "5678"}, {}, "workload_no_matching_policy"),
            ("renamed_repository", {"repository": "acme/other"}, {}, "workload_no_matching_policy"),
            ("other_ref", {"ref": "refs/heads/feature"}, {}, "workload_no_matching_policy"),
            ("missing_condition_claim", {"ref": None}, {}, "workload_no_matching_policy"),
            ("empty_condition_claim", {"ref": ""}, {}, "workload_no_matching_policy"),
            ("condition_claim_not_a_string", {"ref": ["refs/heads/main"]}, {}, "workload_no_matching_policy"),
            ("condition_claim_with_a_nul_character", {"ref": "refs/heads/main\x00"}, {}, "workload_no_matching_policy"),
            ("empty_subject", {"repository_id": ""}, {}, "workload_token_invalid"),
            ("missing_subject_name", {"repository": None}, {}, "workload_token_invalid"),
            (
                "unknown_project",
                {},
                {"resource": f"{_SITE_URL}/api/projects/999999999"},
                "workload_no_matching_policy",
            ),
            ("bad_resource", {}, {"resource": "https://evil.example.com/api/projects/1"}, "workload_invalid_request"),
            (
                "unsupported_token_type",
                {},
                {"subject_token_type": "urn:ietf:params:oauth:token-type:refresh_token"},
                "workload_invalid_request",
            ),
        ]
    )
    def test_exchange_refuses(
        self, _name: str, claim_overrides: dict[str, Any], request_overrides: dict[str, str], error_code: str
    ) -> None:
        response = self._exchange(_oidc_token(**claim_overrides), **request_overrides)

        assert response.status_code >= 400
        assert response.json()["error_code"] == error_code, response.json()
        assert response.json()["error_uri"].endswith(f"#{error_code}")

    def test_exchange_asks_for_a_retry_when_the_provider_keys_cannot_be_fetched(self) -> None:
        cache.clear()
        with patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document",
            side_effect=CIMDFetchError("connection timed out"),
        ):
            response = self._exchange()

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.json()
        assert response.json()["error"] == "temporarily_unavailable"
        assert response.json()["error_code"] == "workload_provider_unavailable"

    def test_exchange_refuses_a_token_signed_by_another_key(self) -> None:
        response = self._exchange(_oidc_token(signing_key=_OTHER_KEY_PEM))

        assert response.json()["error_code"] == "workload_token_invalid"

    def test_exchange_matches_only_policies_of_the_named_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self.policy.delete()
        self._create_policy(team=other_team)

        response = self._exchange()

        assert response.json()["error_code"] == "workload_no_matching_policy"

    def test_an_environment_id_reads_like_a_project_without_a_policy(self) -> None:
        environment = Team.objects.create(organization=self.organization, project=self.project, name="Staging")

        response = self._exchange(resource=f"{_SITE_URL}/api/projects/{environment.id}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error_code"] == "workload_no_matching_policy"

    def test_exchange_points_to_a_pending_request(self) -> None:
        self.policy.delete()
        pending = WorkloadTrustPolicyRequest.objects.for_team(self.team.id).create(
            team=self.team,
            name="Production deploys",
            issuer=FAKE_WORKLOAD_ISSUER,
            subject_name="acme/web",
            subject="1234",
            conditions={"ref": "refs/heads/main"},
            scopes=["annotation:write"],
        )

        body = self._exchange().json()

        assert body["error_code"] == "workload_policy_request_pending"
        assert body["approval_url"] == f"{_SITE_URL}/project/{self.team.id}/workload-trust-policy-requests/{pending.pk}"

    @parameterized.expand(
        [
            (
                "more_conditions_win",
                {"environment": "production", "ref": "refs/heads/main"},
                {},
                "error_tracking:write",
            ),
            (
                "a_condition_the_token_fails_never_matches",
                {"environment": "staging", "ref": "refs/heads/main"},
                {},
                "annotation:write",
            ),
            (
                "a_condition_whose_claim_the_token_lacks_never_matches",
                {"environment": "production", "ref": "refs/heads/main"},
                {"environment": None},
                "annotation:write",
            ),
            (
                "a_stored_condition_the_provider_does_not_allow_never_matches",
                {"ref": "refs/heads/main", "sha": "abc123"},
                {},
                "annotation:write",
            ),
        ]
    )
    def test_the_most_specific_matching_policy_wins(
        self, _name: str, conditions: dict[str, str], claim_overrides: dict[str, Any], expected_scope: str
    ) -> None:
        self._create_policy(conditions=conditions, scopes=["error_tracking:write"])

        body = self._exchange(_oidc_token(**claim_overrides)).json()

        assert body["scope"] == expected_scope, body

    def test_token_never_outlives_the_oidc_token(self) -> None:
        body = self._exchange(_oidc_token(exp=int(time.time()) + 90)).json()

        assert 0 < body["expires_in"] <= 90

    @parameterized.expand([("policy_disabled",), ("policy_narrowed",), ("policy_deleted",), ("owner_demoted",)])
    def test_token_stops_working(self, case: str) -> None:
        token = self._access_token()
        path = f"/api/projects/{self.team.id}/annotations/"
        assert self._call("get", path, token).status_code == status.HTTP_200_OK

        with self.captureOnCommitCallbacks(execute=True):
            if case == "policy_disabled":
                self.policy.enabled = False
                self.policy.save()
            elif case == "policy_narrowed":
                self.policy.conditions = {"ref": "refs/heads/release"}
                self.policy.save()
            elif case == "policy_deleted":
                self.policy.delete()
            else:
                self.organization_membership.level = OrganizationMembership.Level.ADMIN
                self.organization_membership.save()

        assert self._call("get", path, token).status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand([("expired",), ("signed_by_another_key",)])
    def test_api_refuses_an_expired_or_forged_token(self, case: str) -> None:
        token = self._access_token()
        path = f"/api/projects/{self.team.id}/annotations/"

        if case == "expired":
            with time_machine.travel(timezone.now() + timedelta(hours=1), tick=False):
                response = self._call("get", path, token)
        else:
            claims = jwt.decode(token, options={"verify_signature": False})
            forged = jwt.encode(
                claims, generate_rsa_private_key_pem(), algorithm="RS256", headers=jwt.get_unverified_header(token)
            )
            response = self._call("get", path, forged)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()

    def test_token_is_pinned_to_its_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_org = Organization.objects.create(name="Other org")
        foreign_team = Team.objects.create(organization=other_org, name="Foreign")
        OrganizationMembership.objects.create(
            organization=other_org, user=self.user, level=OrganizationMembership.Level.OWNER
        )
        token = self._access_token()

        same_org = self._call("get", f"/api/projects/{other_team.id}/annotations/", token)
        other_org_response = self._call("get", f"/api/projects/{foreign_team.id}/annotations/", token)
        organization_level = self._call("get", f"/api/organizations/{self.organization.id}/members/", token)
        self.user.is_staff = True
        self.user.save()
        with override_settings(CLOUD_DEPLOYMENT="US"):
            staff_bypass = self._call(
                "get",
                f"/api/organizations/{other_org.id}/legal_documents/00000000-0000-0000-0000-000000000000/download/",
                token,
            )

        assert same_org.status_code == status.HTTP_403_FORBIDDEN
        assert other_org_response.status_code == status.HTTP_403_FORBIDDEN
        assert organization_level.status_code == status.HTTP_403_FORBIDDEN
        assert staff_bypass.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_scope_gets_the_insufficient_scope_challenge(self) -> None:
        token = self._access_token()

        response = self._call("get", f"/api/projects/{self.team.id}/insights/", token)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response["WWW-Authenticate"] == 'Bearer error="insufficient_scope", scope="insight:read"'
        assert response.json()["extra"]["missing_scopes"] == ["insight:read"]

    @parameterized.expand(
        [
            ("list_policies", "get", "workload_trust_policies/"),
            ("list_providers", "get", "workload_trust_policies/providers/"),
            ("create_policy", "post", "workload_trust_policies/"),
            ("list_requests", "get", "workload_trust_policy_requests/"),
            ("create_request", "post", "workload_trust_policy_requests/"),
            ("approve_request", "post", "workload_trust_policy_requests/00000000-0000-0000-0000-000000000001/approve/"),
        ]
    )
    def test_workload_tokens_cannot_reach_trust_policy_endpoints(self, _name: str, method: str, path: str) -> None:
        token = self._access_token()

        response = self._call(method, f"/api/projects/{self.team.id}/{path}", token)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert "WWW-Authenticate" not in response

    def test_a_staff_owners_workload_token_does_not_get_the_mcp_registry_staff_tier(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.policy.scopes = ["mcp_registry:read"]
        self.policy.save()
        token = self._access_token()

        with patch(
            "posthoganalytics.feature_enabled", side_effect=lambda flag_key, *_, **__: flag_key == "mcp-registry"
        ):
            response = self._call("get", f"/api/projects/{self.team.id}/mcp_registry/servers/measured_projects/", token)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    @parameterized.expand(
        [
            ("mcp_server_installations", ["project:read"], "get", "mcp_server_installations/"),
            # The view's own personal API key authenticator rejects the token before the permission runs.
            (
                "posthog_connection_forward",
                ["integration:write", "project:read"],
                "post",
                "posthog_connections/1/forward/",
            ),
            ("github_link_existing", ["integration:write"], "post", "integrations/github/link_existing/"),
        ]
    )
    def test_workload_tokens_cannot_use_the_owners_own_connections(
        self, _name: str, scopes: list[str], method: str, path: str
    ) -> None:
        self.policy.scopes = scopes
        self.policy.save()
        token = self._access_token()

        response = self._call(method, f"/api/environments/{self.team.id}/{path}", token)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), response.json()

    def test_workload_tokens_see_no_connection_state_in_the_canvas_connector_catalog(self) -> None:
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="12345",
            config={"installation_id": "12345", "account": {"type": "User", "name": "octocat"}},
            sensitive_config={"access_token": "ghs_test", "user_access_token": "ghu_test"},
        )
        self.policy.scopes = ["canvas:read"]
        self.policy.save()
        token = self._access_token()

        with patch("products.canvas.backend.presentation.views.canvas_connectors_enabled", return_value=True):
            response = self._call("get", f"/api/projects/{self.team.id}/canvases/connectors/", token)

        assert response.status_code == status.HTTP_200_OK, response.json()
        github = next(entry for entry in response.json()["connectors"] if entry["provider"] == "github")
        assert github["connected"] is None

    def test_a_staff_owners_workload_token_cannot_change_global_dashboard_templates(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.policy.scopes = ["dashboard_template:write"]
        self.policy.save()
        template = DashboardTemplate.objects.create(template_name="Global", scope=DashboardTemplate.Scope.GLOBAL)
        token = self._access_token()

        response = self._call(
            "patch",
            f"/api/projects/{self.team.id}/dashboard_templates/{template.id}/",
            token,
            {"template_name": "Changed"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        template.refresh_from_db()
        assert template.template_name == "Global"

    def test_project_read_hides_secrets_from_workload_tokens_but_not_personal_api_keys(self) -> None:
        self.team.secret_api_token = "phs_example_team_secret"
        self.team.save()
        self.policy.scopes = ["project:read"]
        self.policy.save()
        token = self._access_token()
        personal_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="pat", secure_value=hash_key_value(personal_key), scopes=["*"]
        )

        workload_body = self._call("get", f"/api/projects/{self.team.id}/", token).json()
        pat_body = self._call("get", f"/api/projects/{self.team.id}/", personal_key).json()

        assert workload_body["api_token"] == self.team.api_token
        assert not {
            "secret_api_token",
            "secret_api_token_backup",
            "heatmaps_screenshot_secret",
            "live_events_token",
        } & set(workload_body)
        assert pat_body["secret_api_token"] == "phs_example_team_secret"
