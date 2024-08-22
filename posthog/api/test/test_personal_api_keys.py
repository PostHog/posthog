from datetime import timedelta

from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.insight import Insight
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.schema import EventsQuery
from posthog.test.base import APIBaseTest


class TestPersonalAPIKeysAPI(APIBaseTest):
    def test_create_personal_api_key(self):
        label = "Test key uno"
        response = self.client.post(
            "/api/personal_api_keys",
            {"label": label, "scopes": ["insight:read"], "scoped_organizations": [], "scoped_teams": []},
        )
        assert response.status_code == 201
        data = response.json()

        key = PersonalAPIKey.objects.get(id=data["id"])

        assert response.json() == {
            "id": key.id,
            "label": label,
            "created_at": data["created_at"],
            "last_used_at": None,
            "user_id": self.user.id,
            "scopes": ["insight:read"],
            "scoped_organizations": [],
            "scoped_teams": [],
            "value": data["value"],
            "mask_value": data["mask_value"],
        }
        assert data["value"].startswith("phx_")  # Personal API key prefix

    def test_create_too_many_api_keys(self):
        for i in range(0, 10):
            self.client.post(
                "/api/personal_api_keys",
                {"label": i, "scopes": ["insight:read"], "scoped_organizations": [], "scoped_teams": []},
            )
        response = self.client.post(
            "/api/personal_api_keys",
            {"label": i, "scopes": ["insight:read"], "scoped_organizations": [], "scoped_teams": []},
        )
        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "You can only have 10 personal API keys. Remove an existing key before creating a new one.",
            "attr": None,
        }

    def test_create_personal_api_key_label_required(self):
        response = self.client.post("/api/personal_api_keys/", {"label": ""})
        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "blank",
            "detail": "This field may not be blank.",
            "attr": "label",
        }

    def test_create_personal_api_key_scopes_required(self):
        response = self.client.post("/api/personal_api_keys/", {"label": "test"})
        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "scopes",
        }

    def test_update_api_key(self):
        key = PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=[
                "insight:read",
            ],
        )
        response = self.client.patch(
            f"/api/personal_api_keys/{key.id}", {"label": "test-update", "scopes": ["insight:write"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == key.id
        assert data["label"] == "test-update"
        assert data["scopes"] == ["insight:write"]

    def test_allows_all_scope(self):
        response = self.client.post(
            "/api/personal_api_keys/",
            {"label": "test", "scopes": ["*"], "scoped_organizations": [], "scoped_teams": []},
        )
        assert response.status_code == 201
        assert response.json()["scopes"] == ["*"]

    def test_only_allows_valid_scopes(self):
        response = self.client.post("/api/personal_api_keys/", {"label": "test", "scopes": ["invalid"]})
        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "Invalid scope: invalid",
            "attr": "scopes",
        }

        response = self.client.post("/api/personal_api_keys/", {"label": "test", "scopes": ["insight:invalid"]})
        assert response.status_code == 400

    def test_delete_personal_api_key(self):
        key = PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
        )
        assert PersonalAPIKey.objects.count() == 1
        response = self.client.delete(f"/api/personal_api_keys/{key.id}/")
        assert response.status_code == 204
        assert PersonalAPIKey.objects.count() == 0

    def test_list_only_user_personal_api_keys(self):
        my_label = "Test"
        my_key = PersonalAPIKey.objects.create(
            label=my_label,
            user=self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
        )
        other_user = self._create_user("abc@def.xyz")
        PersonalAPIKey.objects.create(
            label="Other test",
            user=other_user,
            secure_value=hash_key_value(generate_random_token_personal()),
        )
        assert PersonalAPIKey.objects.count() == 2
        response = self.client.get("/api/personal_api_keys")
        assert response.status_code == 200
        response_data = response.json()
        assert len(response_data) == 1
        response_data[0].pop("created_at")
        assert response_data[0] == {
            "id": my_key.id,
            "label": my_label,
            "last_used_at": None,
            "user_id": self.user.id,
            "scopes": ["*"],
            "scoped_organizations": None,
            "scoped_teams": None,
            "value": None,
            "mask_value": my_key.mask_value,
        }

    def test_get_own_personal_api_key(self):
        my_label = "Test"
        my_key = PersonalAPIKey.objects.create(
            label=my_label,
            user=self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
        )
        response = self.client.get(f"/api/personal_api_keys/{my_key.id}/")
        assert response.status_code == 200
        assert response.json()["id"] == my_key.id

    def test_get_someone_elses_personal_api_key(self):
        other_user = self._create_user("abc@def.xyz")
        other_key = PersonalAPIKey.objects.create(
            label="Other test",
            user=other_user,
            secure_value=hash_key_value(generate_random_token_personal()),
        )
        response = self.client.get(f"/api/personal_api_keys/{other_key.id}/")
        assert response.status_code == 404
        response_data = response.json()
        assert response_data, self.not_found_response()

    def test_organization_scoping(self):
        response = self.client.post(
            "/api/personal_api_keys/",
            {"label": "test", "scopes": ["*"], "scoped_organizations": [str(self.organization.id)], "scoped_teams": []},
        )
        assert response.status_code == 201, response.json()
        assert response.json()["scoped_organizations"] == [str(self.organization.id)]

    def test_organization_scoping_forbids_other(self):
        other_org = Organization.objects.create(name="other org")
        response = self.client.post(
            "/api/personal_api_keys/",
            {
                "label": "test",
                "scopes": ["*"],
                "scoped_organizations": [str(self.organization.id), str(other_org.id)],
                "scoped_teams": [],
            },
        )
        assert response.status_code == 400, response.json()
        assert response.json()["detail"] == "You must be a member of all organizations that you are scoping the key to."

    def test_team_scoping(self):
        response = self.client.post(
            "/api/personal_api_keys/",
            {"label": "test", "scopes": ["*"], "scoped_teams": [self.team.id], "scoped_organizations": []},
        )
        assert response.status_code == 201, response.json()
        assert response.json()["scoped_teams"] == [self.team.id]

    def test_team_scoping_forbids_other(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        response = self.client.post(
            "/api/personal_api_keys/",
            {
                "label": "test",
                "scopes": ["*"],
                "scoped_teams": [self.team.id, other_team.id],
                "scoped_organizations": [],
            },
        )
        assert response.status_code == 400, response.json()
        assert response.json()["detail"] == "You must be a member of all teams that you are scoping the key to."


class PersonalAPIKeysBaseTest(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    value: str
    key: PersonalAPIKey

    def _do_request(self, url: str):
        return self.client.get(url, headers={"authorization": f"Bearer {self.value}"})

    def setUp(self):
        other_organization, _, other_team = Organization.objects.bootstrap(self.user)
        self.other_organization = other_organization
        self.other_team = other_team

        self.value = generate_random_token_personal()
        self.key = PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value=hash_key_value(self.value),
            scopes=[],
            scoped_teams=[],
            scoped_organizations=[],
        )
        return super().setUp()


class TestPersonalAPIKeysAPIAuthentication(PersonalAPIKeysBaseTest):
    def setUp(self):
        super().setUp()
        self.value_390000 = generate_random_token_personal()
        self.key_390000 = PersonalAPIKey.objects.create(
            label="Test", user=self.user, secure_value=hash_key_value(self.value_390000, "pbkdf2", iterations=390000)
        )
        self.value_hardcoded = "phx_0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p"
        self.key_hardcoded = PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value="pbkdf2_sha256$260000$posthog_personal_api_key$dUOOjl6bYdigHd+QfhYzN6P2vM01ZbFROS8dm9KRK7Y=",
        )

    def test_no_key(self):
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/")
        assert response.status_code == 401
        assert response.json() == {
            "attr": None,
            "code": "not_authenticated",
            "detail": "Authentication credentials were not provided.",
            "type": "authentication_error",
        }

    def test_header_resilient(self):
        key_before = PersonalAPIKey.objects.get(id=self.key.id).secure_value
        self.assertTrue(key_before.startswith("sha256$"))

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/", headers={"authorization": f"Bearer  {self.value}  "}
        )
        assert response.status_code == 200

        # Retrieve key from db to check that no update was made
        key_after = PersonalAPIKey.objects.get(id=self.key.id).secure_value
        self.assertEqual(key_after, key_before)

    def test_header_alternative_iteration_count(self):
        key_before = PersonalAPIKey.objects.get(id=self.key_390000.id).secure_value
        self.assertTrue(key_before.startswith("pbkdf2_sha256$390000$"))

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/", headers={"authorization": f"Bearer {self.value_390000}"}
        )
        assert response.status_code == 200

        # Retrieve key from db to check if hash was updated to latest mode
        key_after = PersonalAPIKey.objects.get(id=self.key_390000.id).secure_value
        self.assertEqual(key_after, hash_key_value(self.value_390000))
        self.assertNotEqual(key_after, key_before)

    def test_header_hardcoded(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/", headers={"authorization": f"Bearer {self.value_hardcoded}"}
        )
        assert response.status_code == 200

    def test_query_string(self):
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/?personal_api_key={self.value}")
        assert response.status_code == 200

    def test_body(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            {"personal_api_key": self.value},
        )
        assert response.status_code == 200

    def test_user_not_active(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards", headers={"authorization": f"Bearer {self.value}"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_endpoint(self):
        # NOTE: This is not actually supported currently by new scopes but needs to work for pre-scoped api keys
        response = self.client.get("/api/users/@me/", headers={"authorization": f"Bearer {self.value}"})
        assert response.status_code == status.HTTP_200_OK

    def test_does_not_interfere_with_temporary_token_auth(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/", headers={"authorization": f"Bearer {self.value}"}
        )
        assert response.status_code == status.HTTP_200_OK

        impersonated_access_token = encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=15),
            PosthogJwtAudience.IMPERSONATED_USER,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            headers={"authorization": f"Bearer {impersonated_access_token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_cannot_create_other_keys(self):
        response = self.client.post(
            "/api/personal_api_keys",
            {"label": "test", "scopes": ["insight:read"], "scoped_organizations": [], "scoped_teams": []},
            headers={"authorization": f"Bearer {self.value}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()

    def test_cannot_edit_self(self):
        response = self.client.post(
            f"/api/personal_api_keys/{self.key.id}/",
            {"scopes": ["*"]},
            headers={"authorization": f"Bearer {self.value}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()


# NOTE: These tests use feature flags as an example of a scope, but the actual feature flag functionality is not relevant
# It is however a good example of a range of cases
class TestPersonalAPIKeysWithScopeAPIAuthentication(PersonalAPIKeysBaseTest):
    def setUp(self):
        super().setUp()
        self.key.scopes = ["feature_flag:read"]
        self.key.save()

    def test_allows_legacy_api_key_to_access_all(self):
        self.key.scopes = None
        self.key.save()
        response = self._do_request("/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK

    def test_forbids_scoped_access_for_unsupported_endpoint(self):
        # Even * scope isn't allowed for unsupported endpoints
        self.key.scopes = ["*"]
        self.key.save()
        response = self._do_request(f"/api/projects/{self.team.id}/search")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "This action does not support Personal API Key access"

    def test_special_handling_for_teams_still_forbids(self):
        response = self._do_request(f"/api/projects/{self.team.id}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_allows_derived_scope_for_read(self):
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        assert response.status_code == status.HTTP_200_OK

    def test_denies_derived_scope_for_write(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", data={}, headers={"authorization": f"Bearer {self.value}"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "API key missing required scope 'feature_flag:write'"

    def test_allows_action_with_required_scopes(self):
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        assert response.status_code == status.HTTP_200_OK

    def test_errors_for_action_without_required_scopes(self):
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/evaluation_reasons")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "This action does not support Personal API Key access"

    def test_forbids_action_with_other_scope(self):
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/activity")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "API key missing required scope 'activity_log:read'"

    def test_denies_action_with_other_scope_with_updated_scope(self):
        self.key.scopes = ["feature_flag:write", "activity_log:read"]
        self.key.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/activity")
        assert response.status_code == status.HTTP_200_OK

    def test_allows_overriding_write_scopes(self):
        self.key.scopes = ["query:read"]
        self.key.save()

        query = EventsQuery(select=["event", "distinct_id"])
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {"query": query.dict()},
            headers={"authorization": f"Bearer {self.value}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_works_with_routes_missing_action(self):
        insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)

        self.key.scopes = ["sharing_configuration:read"]
        self.key.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}/sharing?personal_api_key={self.value}"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.key.scopes = ["sharing_configuration:write"]
        self.key.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}/sharing?personal_api_key={self.value}"
        )
        assert response.status_code == status.HTTP_200_OK


class TestPersonalAPIKeysWithOrganizationScopeAPIAuthentication(PersonalAPIKeysBaseTest):
    def setUp(self):
        super().setUp()
        self.key.scopes = ["*"]
        self.key.scoped_organizations = [str(self.organization.id)]
        self.key.scoped_teams = []
        self.key.save()

    def test_allows_access_to_scoped_org(self):
        response = self._do_request(f"/api/organizations/{self.organization.id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self._do_request(f"/api/organizations/{self.organization.id}/projects")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_allows_access_to_scoped_org_teams(self):
        response = self._do_request(f"/api/organizations/{self.organization.id}/projects/{self.team.id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_denies_access_to_non_scoped_org_and_team(self):
        response = self._do_request(f"/api/organizations/{self.other_organization.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        response = self._do_request(f"/api/projects/{self.other_team.id}/feature_flags")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_cant_list_all_projecs_for_current_org(self):
        self.user.current_organization = self.organization
        self.user.save()

        response = self._do_request(f"/api/projects")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_allows_user_me_read_access(self):
        # The /users/@me/ endpoint is not team-based, but it's useful as a way of checking whether the key works
        # (e.g. in our Zapier integration), hence it's exempt from org/team scoping
        response = self._do_request(f"/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK, response.json()


class TestPersonalAPIKeysWithTeamScopeAPIAuthentication(PersonalAPIKeysBaseTest):
    def setUp(self):
        super().setUp()
        self.key.scopes = ["*"]
        self.key.scoped_organizations = []
        self.key.scoped_teams = [self.team.id]
        self.key.save()

    def test_allows_access_to_team_resources(self):
        response = self._do_request(f"/api/organizations/{self.organization.id}/projects/{self.team.id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self._do_request(f"/api/projects/{self.team.id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_cant_list_all_projecs(self):
        response = self._do_request(f"/api/projects")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_denies_access_to_org_resources(self):
        response = self._do_request(f"/api/organizations/{self.organization.id}/projects")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        response = self._do_request(f"/api/organizations/{self.organization.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_denies_access_to_non_scoped_org_and_team(self):
        response = self._do_request(f"/api/organizations/{self.other_organization.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        response = self._do_request(f"/api/projects/{self.other_team.id}/feature_flags")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        response = self._do_request(f"/api/projects/{self.other_team.id}")

    def test_allows_user_me_read_access(self):
        # The /users/@me/ endpoint is not team-based, but it's useful as a way of checking whether the key works
        # (e.g. in our Zapier integration), hence it's exempt from org/team scoping
        response = self._do_request(f"/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK, response.json()
