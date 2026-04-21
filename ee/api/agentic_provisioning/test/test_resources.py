from django.test import override_settings

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningResources(StripeProvisioningTestBase):
    def test_create_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_get_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)

    def test_get_resource_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999",
            token=token,
        )
        assert res.status_code == 403

    def test_get_resource_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number",
            token=token,
        )
        assert res.status_code == 400

    def test_create_resource_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/resources", data={"service_id": "analytics"})
        assert res.status_code == 401

    def test_create_resource_invalid_bearer_returns_401(self):
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token="pha_invalid_token",
        )
        assert res.status_code == 401

    def test_get_resource_missing_bearer_returns_401(self):
        res = self._get_signed(f"/api/agentic/provisioning/resources/{self.team.id}")
        assert res.status_code == 401

    def test_get_resource_returns_service_id_from_create(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.json()["service_id"] == "analytics"

    def test_get_resource_defaults_service_id_without_create(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.json()["service_id"] == "analytics"

    def test_create_resource_defaults_service_id_to_analytics(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["service_id"] == "analytics"

    def test_create_resource_includes_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 200
        personal_api_key = res.json()["complete"]["access_configuration"]["personal_api_key"]
        assert personal_api_key.startswith("phx_")

    def test_create_resource_creates_pat_for_user(self):
        initial_count = PersonalAPIKey.objects.filter(user=self.user).count()
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert PersonalAPIKey.objects.filter(user=self.user).count() == initial_count + 1

    def test_create_resource_pat_label_contains_stripe_projects(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.label.startswith("Stripe Projects")

    def test_create_resource_does_not_delete_existing_pats(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        first_pat = PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects").first()
        assert first_pat is not None

        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        stripe_pats = PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects")
        assert stripe_pats.count() == 2
        assert PersonalAPIKey.objects.filter(id=first_pat.id).exists()

    def test_create_resource_with_project_id_creates_new_team(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_123"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        new_team_id = int(data["id"])
        assert new_team_id != self.team.id
        assert data["complete"]["access_configuration"]["api_key"] != self.team.api_token

    def test_create_resource_same_project_id_returns_same_team(self):
        token = self._get_bearer_token()
        res1 = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_456"},
            token=token,
        )
        res2 = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_456"},
            token=token,
        )
        assert res1.json()["id"] == res2.json()["id"]

    def test_create_resource_different_project_ids_create_different_teams(self):
        token = self._get_bearer_token()
        res1 = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_a"},
            token=token,
        )
        res2 = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_b"},
            token=token,
        )
        assert res1.json()["id"] != res2.json()["id"]

    def test_create_resource_with_project_id_adds_to_scoped_teams(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_scope"},
            token=token,
        )
        access_token = OAuthAccessToken.objects.get(token=token)
        assert len(access_token.scoped_teams) == 2
        assert self.team.id in access_token.scoped_teams

    def test_create_resource_without_project_id_returns_existing_team(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.json()["id"] == str(self.team.id)

    def test_create_resource_with_project_id_and_name(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "service_id": "analytics",
                "project_id": "proj_named",
                "configuration": {"project_name": "My App"},
            },
            token=token,
        )
        assert res.status_code == 200
        new_team = Team.objects.get(id=int(res.json()["id"]))
        assert new_team.name == "My App"

    def test_create_resource_new_team_belongs_to_same_org(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_org"},
            token=token,
        )
        new_team = Team.objects.get(id=int(res.json()["id"]))
        assert new_team.organization_id == self.team.organization_id

    def test_get_resource_does_not_include_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        assert "personal_api_key" not in res.json()["complete"]["access_configuration"]
