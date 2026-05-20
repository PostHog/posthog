from posthog.test.base import APIBaseTest

from posthog.api.project_secret_api_key import MAX_PROJECT_SECRET_API_KEYS_PER_TEAM
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.project_secret_api_key import ProjectSecretAPIKey


class TestProjectSecretAPIKeysAPIMember(APIBaseTest):
    def test_create_forbidden(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "nope", "scopes": ["endpoint:read"]},
        )
        assert response.status_code == 403

    def test_update_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "admin-created", "scopes": ["endpoint:read"]},
        )
        key_id = create_response.json()["id"]

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}",
            {"label": "updated"},
        )
        assert response.status_code == 403

    def test_delete_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "admin-created", "scopes": ["endpoint:read"]},
        )
        key_id = create_response.json()["id"]

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}")
        assert response.status_code == 403

    def test_list_allowed(self):
        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        assert response.status_code == 200


class TestProjectSecretAPIKeysAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_create_project_secret_api_key(self):
        label = "the key to rule them all"
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys", {"label": label, "scopes": ["endpoint:read"]}
        )
        assert response.status_code == 201
        data = response.json()

        key = ProjectSecretAPIKey.objects.get(id=data["id"])
        assert data["id"] == key.id
        assert data["label"] == label
        assert data["scopes"] == ["endpoint:read"]
        assert data["last_rolled_at"] is None
        assert data["last_used_at"] is None
        assert data["value"].startswith("phs_")

    def test_create_too_many_api_keys(self):
        for i in range(0, MAX_PROJECT_SECRET_API_KEYS_PER_TEAM):
            self.client.post(
                f"/api/projects/{self.team.id}/project_secret_api_keys",
                {"label": i, "scopes": ["endpoint:read"]},
            )
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "not the one", "scopes": ["endpoint:read"]},
        )
        assert response.status_code == 400
        self.assertIn("You can only have", response.json()["detail"])

    def test_label_required(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "", "scopes": ["endpoint:read"]},
        )
        assert response.status_code == 400

    def test_scopes_required(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key"},
        )
        assert response.status_code == 400

    def test_wildcard_scope_not_allowed(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key", "scopes": ["*"]},
        )
        assert response.status_code == 400
        assert "Wildcard" in response.json()["detail"]

    def test_only_allowed_scopes_accepted(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key", "scopes": ["insight:read"]},
        )
        assert response.status_code == 400
        assert "can not be assigned" in response.json()["detail"]

    def test_invalid_scope_format_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key", "scopes": ["notavalidscope"]},
        )
        assert response.status_code == 400
        assert "Invalid scope" in response.json()["detail"]

    def test_update_label(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "original", "scopes": ["endpoint:read"]},
        )
        key_id = create_response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}",
            {"label": "updated"},
        )
        assert response.status_code == 200
        assert response.json()["label"] == "updated"

    def test_update_scopes_to_empty_rejected(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key", "scopes": ["endpoint:read"]},
        )
        key_id = create_response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}",
            {"scopes": []},
        )
        assert response.status_code == 400

    def test_delete(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "deleteme", "scopes": ["endpoint:read"]},
        )
        key_id = create_response.json()["id"]

        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}")
        assert response.status_code == 204
        assert not ProjectSecretAPIKey.objects.filter(id=key_id).exists()

    def test_roll(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "rollme", "scopes": ["endpoint:read"]},
        )
        data = create_response.json()
        key_id = data["id"]
        original_mask = data["mask_value"]
        original_secure_value = ProjectSecretAPIKey.objects.get(id=key_id).secure_value

        response = self.client.post(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}/roll")
        assert response.status_code == 200
        rolled = response.json()

        assert rolled["label"] == "rollme"
        assert rolled["scopes"] == ["endpoint:read"]
        assert rolled["mask_value"] != original_mask
        assert rolled["last_rolled_at"] is not None
        assert rolled["value"] is not None
        assert rolled["value"].startswith("phs_")

        key = ProjectSecretAPIKey.objects.get(id=key_id)
        assert key.secure_value != original_secure_value

    def test_list_only_current_team_keys(self):
        self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "team1 key", "scopes": ["endpoint:read"]},
        )

        other_team = Team.objects.create(organization=self.organization, name="other team")
        ProjectSecretAPIKey.objects.create(
            team=other_team,
            label="team2 key",
            secure_value="sha256$abc123",
            mask_value="phs_...1234",
            scopes=["endpoint:read"],
        )

        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["label"] == "team1 key"

    def test_cannot_access_other_teams_keys(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        ProjectSecretAPIKey.objects.create(
            team=other_team,
            label="secret",
            secure_value="sha256$other",
            mask_value="phs_...5678",
            scopes=["endpoint:read"],
        )

        response = self.client.get(f"/api/projects/{other_team.id}/project_secret_api_keys")
        assert response.status_code == 403

    def test_duplicate_label_rejected(self):
        self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "unique-name", "scopes": ["endpoint:read"]},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "unique-name", "scopes": ["endpoint:read"]},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_value_only_returned_on_create(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "my key", "scopes": ["endpoint:read"]},
        )
        assert create_response.json()["value"] is not None

        key_id = create_response.json()["id"]
        get_response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}")
        assert get_response.json()["value"] is None

    def test_activity_log_on_create(self):
        from posthog.models.activity_logging.activity_log import ActivityLog

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "logged key", "scopes": ["endpoint:read"]},
        )
        key_id = response.json()["id"]

        logs = ActivityLog.objects.filter(scope="ProjectSecretAPIKey", item_id=str(key_id), activity="created")
        assert len(logs) == 1

        log = logs[0]
        assert log.team_id == self.team.id
        assert log.organization_id == self.organization.id
        assert log.user == self.user
        assert log.detail is not None
        assert log.detail["name"] == "logged key"

        context = log.detail["context"]
        assert context["organization_name"] == self.organization.name
        assert context["project_name"] == self.team.name
        assert context["scopes"] == ["endpoint:read"]
        assert context["created_by_email"] == self.user.email

    def test_activity_log_on_update(self):
        from posthog.models.activity_logging.activity_log import ActivityLog

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "label_before", "scopes": ["endpoint:read"]},
        )
        key_id = response.json()["id"]

        self.client.patch(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}",
            {"label": "label_after"},
        )

        logs = ActivityLog.objects.filter(scope="ProjectSecretAPIKey", item_id=str(key_id), activity="updated")
        assert len(logs) == 1
        assert logs[0].detail is not None

        changes = logs[0].detail["changes"]
        label_change = next(c for c in changes if c["field"] == "label")
        assert label_change["before"] == "label_before"
        assert label_change["after"] == "label_after"

    def test_activity_log_on_roll(self):
        from posthog.models.activity_logging.activity_log import ActivityLog

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "roll me", "scopes": ["endpoint:read"]},
        )
        key_id = response.json()["id"]

        self.client.post(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}/roll")

        logs = ActivityLog.objects.filter(scope="ProjectSecretAPIKey", item_id=str(key_id), activity="updated")
        assert len(logs) == 1
        assert logs[0].detail is not None
        assert logs[0].detail["name"] == "roll me"
        changes = {c["field"]: c for c in logs[0].detail["changes"]}
        assert "secure_value" not in changes
        assert "mask_value" in changes
        assert "last_rolled_at" in changes

        assert changes["mask_value"]["before"] != changes["mask_value"]["after"]
        assert changes["mask_value"]["after"].startswith("phs_...")
        assert changes["last_rolled_at"]["before"] is None
        assert changes["last_rolled_at"]["after"] is not None

    def test_activity_log_on_delete(self):
        from posthog.models.activity_logging.activity_log import ActivityLog

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "delete me", "scopes": ["endpoint:read"]},
        )
        key_id = response.json()["id"]

        self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}")

        logs = ActivityLog.objects.filter(scope="ProjectSecretAPIKey", item_id=str(key_id), activity="deleted")
        assert len(logs) == 1
        assert logs[0].detail is not None
        assert logs[0].detail["name"] == "delete me"
        assert logs[0].team_id == self.team.id
