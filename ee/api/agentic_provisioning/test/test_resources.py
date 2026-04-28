from django.test import override_settings

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningResources(ProvisioningTestBase):
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

    def test_create_resource_pat_label_contains_provisioning_prefix(self):
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
        provisioning_pats = PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects")
        assert provisioning_pats.count() == 2
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

    def test_create_resource_race_winner_in_different_org_does_not_leak_cross_org(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.models.organization import Organization
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_org = Organization.objects.create(name="Foreign Org")
        foreign_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=other_org,
            name="Foreign project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=foreign_team, defaults={"stripe_project_id": "proj_shared"}
        )

        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        calls: list[int] = []

        def raise_once_then_passthrough(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        token = self._get_bearer_token()
        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=raise_once_then_passthrough):
            res = self._post_signed_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"service_id": "analytics", "project_id": "proj_shared"},
                token=token,
            )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "project_id_conflict"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert foreign_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_race_winner_in_same_org_returns_winner_and_syncs_scopes(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        winner_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Race winner",
        )

        project_id = "proj_race_same_org"
        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        raced: list[int] = []

        def race_then_raise(*args, **kwargs):
            defaults = kwargs.get("defaults", {})
            if "stripe_project_id" in defaults and not raced:
                raced.append(1)
                original_update_or_create(team=winner_team, defaults={"stripe_project_id": project_id})
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        token = self._get_bearer_token()
        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=race_then_raise):
            res = self._post_signed_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"service_id": "analytics", "project_id": project_id},
                token=token,
            )

        assert res.status_code == 200
        assert res.json()["id"] == str(winner_team.id)

        access_token = OAuthAccessToken.objects.get(token=token)
        assert winner_team.id in (access_token.scoped_teams or [])
        assert self.team.id in (access_token.scoped_teams or [])

    def test_create_resource_with_existing_project_id_adds_resolved_team_to_scoped_teams(self):
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        existing_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Pre-existing project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=existing_team, defaults={"stripe_project_id": "proj_existing"}
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.scoped_teams == [self.team.id]

        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_existing"},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["id"] == str(existing_team.id)

        access_token.refresh_from_db()
        assert existing_team.id in access_token.scoped_teams
        assert self.team.id in access_token.scoped_teams

    def test_create_resource_with_existing_project_id_rejects_when_user_lacks_team_access(self):
        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=restricted_team, defaults={"stripe_project_id": "proj_restricted"}
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics", "project_id": "proj_restricted"},
            token=token,
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert restricted_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_race_winner_rejects_when_user_lacks_team_access(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted race winner",
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        project_id = "proj_race_restricted"
        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        raced: list[int] = []

        def race_then_raise(*args, **kwargs):
            defaults = kwargs.get("defaults", {})
            if "stripe_project_id" in defaults and not raced:
                raced.append(1)
                original_update_or_create(team=restricted_team, defaults={"stripe_project_id": project_id})
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        token = self._get_bearer_token()
        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=race_then_raise):
            res = self._post_signed_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"service_id": "analytics", "project_id": project_id},
                token=token,
            )

        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert restricted_team.id not in (access_token.scoped_teams or [])

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
