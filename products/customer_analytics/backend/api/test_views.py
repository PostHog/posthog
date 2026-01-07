from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team

from products.customer_analytics.backend.models import CustomerProfileConfig


class TestCustomerProfileConfigViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/environments/{self.team.id}/customer_profile_configs/"
        self.valid_data = {
            "scope": "person",
            "content": [{"type": "ph-node-foo", "index": 0}],
            "sidebar": [{"type": "ph-node-bar"}],
        }

    def assertActivityLog(self, config_id, activity):
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="CustomerProfileConfig", activity=activity)
        assert logs.count() == 1
        log = logs.latest("created_at")
        assert log.item_id == str(config_id)

    def test_create_customer_profile_config_success(self):
        response = self.client.post(self.endpoint_base, self.valid_data, format="json")

        assert status.HTTP_201_CREATED == response.status_code, response.json()
        response_data = response.json()

        assert "id" in response_data
        assert "person" == response_data["scope"]
        assert self.valid_data["content"] == response_data["content"]
        assert self.valid_data["sidebar"] == response_data["sidebar"]
        assert "created_at" in response_data
        assert "updated_at" in response_data

        config = CustomerProfileConfig.objects.get(id=response_data["id"])
        assert config.scope == "person", "Should persist data"
        assert config.team == self.team
        assert config.content == self.valid_data["content"]
        assert config.sidebar == self.valid_data["sidebar"]
        assert config.created_by == self.user
        self.assertActivityLog(config.id, "created")

    def test_list_customer_profile_configs(self):
        config1 = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"type": "person"})
        config2 = CustomerProfileConfig.objects.create(team=self.team, scope="group_0", content={"type": "group"})
        other_team = Team.objects.create(organization=self.organization)
        CustomerProfileConfig.objects.create(team=other_team, scope="person", content={"type": "other"})

        response = self.client.get(self.endpoint_base)

        assert status.HTTP_200_OK == response.status_code
        response_data = response.json()
        assert response_data["count"] == 2, "Should only return configs for current team"
        config_ids = [config["id"] for config in response_data["results"]]
        assert str(config1.id) in config_ids
        assert str(config2.id) in config_ids

    def test_retrieve_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(
            team=self.team, scope="person", content=self.valid_data["content"], sidebar=self.valid_data["sidebar"]
        )

        response = self.client.get(f"{self.endpoint_base}{config.id}/")

        assert status.HTTP_200_OK == response.status_code
        response_data = response.json()
        assert str(config.id) == response_data["id"]
        assert "person" == response_data["scope"]
        assert self.valid_data["content"] == response_data["content"]
        assert self.valid_data["sidebar"] == response_data["sidebar"]

    def test_update_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"old": "data"})
        update_data = {"scope": "group_0", "content": {"new": "data"}, "sidebar": {"updated": "sidebar"}}

        response = self.client.patch(f"{self.endpoint_base}{config.id}/", update_data, format="json")

        assert status.HTTP_200_OK == response.status_code
        response_data = response.json()

        assert "group_0" == response_data["scope"]
        assert update_data["content"] == response_data["content"]
        assert update_data["sidebar"] == response_data["sidebar"]

        config.refresh_from_db()
        assert "group_0" == config.scope
        assert update_data["content"] == config.content, "Should update database"
        self.assertActivityLog(config.id, "updated")

    def test_delete_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"test": "data"})
        config_id = str(config.id)

        response = self.client.delete(f"{self.endpoint_base}{config.id}/")

        assert status.HTTP_204_NO_CONTENT == response.status_code
        assert not CustomerProfileConfig.objects.filter(id=config.id).exists()
        self.assertActivityLog(config_id, "deleted")

    @parameterized.expand(
        [
            (
                "invalid_scope",
                {"scope": "quick"},
                {
                    "attr": "scope",
                    "type": "validation_error",
                    "code": "invalid_choice",
                    "detail": '"quick" is not a valid choice.',
                },
            ),
            (
                "content_not_dict",
                {"scope": "person", "content": "not_a_dict"},
                {
                    "attr": "content",
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Invalid value for field 'content'",
                },
            ),
            (
                "sidebar_not_dict",
                {"scope": "person", "content": {}, "sidebar": "not_a_dict"},
                {
                    "attr": "sidebar",
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Invalid value for field 'sidebar'",
                },
            ),
            (
                "missing_scope",
                {},
                {"attr": "scope", "type": "validation_error", "code": "required", "detail": "This field is required."},
            ),
        ]
    )
    def test_validation_errors(self, name, invalid_data, expected_response):
        response = self.client.post(self.endpoint_base, invalid_data, format="json")

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        response_data = response.json()
        assert response_data == expected_response

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        other_config = CustomerProfileConfig.objects.create(team=other_team, scope="person", content={"other": "team"})

        response = self.client.get(f"{self.endpoint_base}{other_config.id}/")
        assert status.HTTP_404_NOT_FOUND == response.status_code

        response = self.client.patch(f"{self.endpoint_base}{other_config.id}/", {"scope": "group_0"}, format="json")
        assert status.HTTP_404_NOT_FOUND == response.status_code

        response = self.client.delete(f"{self.endpoint_base}{other_config.id}/")
        assert status.HTTP_404_NOT_FOUND == response.status_code

    def test_scope_choices_validation(self):
        valid_scopes = ["person", "group_0", "group_1", "group_2", "group_3", "group_4"]

        for scope in valid_scopes:
            data = {"scope": scope, "content": {}}
            response = self.client.post(self.endpoint_base, data, format="json")
            assert status.HTTP_201_CREATED == response.status_code, f"Failed for scope: {scope}"

    def test_json_fields_defaults(self):
        data = {"scope": "person", "content": None, "sidebar": None}

        response = self.client.post(self.endpoint_base, data, format="json")

        assert status.HTTP_201_CREATED == response.status_code
        response_data = response.json()
        assert {} == response_data["content"], "Should default to empty dict"
        assert {} == response_data["sidebar"], "Should default to empty dict"

    def test_permissions_authentication_required(self):
        self.client.logout()

        endpoints = [
            ("GET", self.endpoint_base),
            ("POST", self.endpoint_base),
            ("GET", f"{self.endpoint_base}test-id/"),
            ("PATCH", f"{self.endpoint_base}test-id/"),
            ("DELETE", f"{self.endpoint_base}test-id/"),
        ]

        for method, url in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
