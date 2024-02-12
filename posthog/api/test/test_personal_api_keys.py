from datetime import timedelta

from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest


class TestPersonalAPIKeysAPI(APIBaseTest):
    def test_create_personal_api_key(self):
        label = "Test key uno"
        response = self.client.post("/api/personal_api_keys", {"label": label, "scopes": ["insight:read"]})
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
            "value": data["value"],
        }
        assert data["value"].startswith("phx_")  # Personal API key prefix

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
            scopes="insight:read",
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
        response = self.client.post("/api/personal_api_keys/", {"label": "test", "scopes": ["*"]})
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
            "value": None,
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


class TestPersonalAPIKeysAPIAuthentication(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    value: str
    key: PersonalAPIKey

    def setUp(self):
        self.value = generate_random_token_personal()
        self.key = PersonalAPIKey.objects.create(label="Test", user=self.user, secure_value=hash_key_value(self.value))
        self.value_390000 = generate_random_token_personal()
        self.key_390000 = PersonalAPIKey.objects.create(
            label="Test", user=self.user, secure_value=hash_key_value(self.value_390000, iterations=390000)
        )
        self.value_hardcoded = "phx_0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p"
        self.key_hardcoded = PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value="pbkdf2_sha256$260000$posthog_personal_api_key$dUOOjl6bYdigHd+QfhYzN6P2vM01ZbFROS8dm9KRK7Y=",
        )
        return super().setUp()

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
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            HTTP_AUTHORIZATION=f"Bearer  {self.value}  ",
        )
        assert response.status_code == 200

    def test_header_alternative_iteration_count(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            HTTP_AUTHORIZATION=f"Bearer {self.value_390000}",
        )
        assert response.status_code == 200

    def test_header_hardcoded(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            HTTP_AUTHORIZATION=f"Bearer {self.value_hardcoded}",
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
        response = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {self.value}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_endpoint(self):
        response = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {self.value}")
        assert response.status_code == status.HTTP_200_OK

    def test_does_not_interfere_with_temporary_token_auth(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            HTTP_AUTHORIZATION=f"Bearer {self.value}",
        )
        assert response.status_code == status.HTTP_200_OK

        impersonated_access_token = encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=15),
            PosthogJwtAudience.IMPERSONATED_USER,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            HTTP_AUTHORIZATION=f"Bearer {impersonated_access_token}",
        )
        assert response.status_code == status.HTTP_200_OK


# NOTE: These tests use feature flags as an example of a scope, but the actual feature flag functionality is not relevant
# It is however a good example of a range of cases
class TestPersonalAPIKeysWithScopeAPIAuthentication(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    value: str
    key: PersonalAPIKey

    def setUp(self):
        self.value = generate_random_token_personal()
        self.key = PersonalAPIKey.objects.create(
            label="Test", user=self.user, secure_value=hash_key_value(self.value), scopes="feature_flag:read"
        )
        return super().setUp()

    def _do_request(self, url: str):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.value}")

    def test_allows_legacy_api_key_to_access_all(self):
        self.key.scopes = None
        self.key.save()
        response = self._do_request("/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK

    def test_forbids_scoped_access_for_unsupported_endpoint(self):
        # Even * scope isn't allowed for unsupported endpoints
        self.key.scopes = "*"
        self.key.save()
        response = self._do_request("/api/users/@me/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "This action does not support Personal API Key access"

    def test_allows_derived_scope_for_read(self):
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        assert response.status_code == status.HTTP_200_OK

    def test_denies_derived_scope_for_write(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={},
            HTTP_AUTHORIZATION=f"Bearer {self.value}",
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
        self.key.scopes = "feature_flag:write,activity_log:read"
        self.key.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/activity")
        assert response.status_code == status.HTTP_200_OK
