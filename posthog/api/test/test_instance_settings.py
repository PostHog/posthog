from constance import config
from rest_framework import status

from posthog.api.instance_settings import get_instance_setting
from posthog.settings import CONSTANCE_CONFIG
from posthog.test.base import APIBaseTest


class TestInstanceSettings(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_list_instance_settings(self):

        response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["count"], len(CONSTANCE_CONFIG))

        # Check an example attribute
        self.assertEqual(json_response["results"][0]["key"], "MATERIALIZED_COLUMNS_ENABLED")
        self.assertEqual(json_response["results"][0]["value"], True)
        self.assertEqual(
            json_response["results"][0]["description"],
            "Whether materialized columns should be created or used at query time",
        )
        self.assertEqual(json_response["results"][0]["value_type"], "bool")
        self.assertEqual(json_response["results"][0]["editable"], False)

        # Check an editable attribute
        for item in json_response["results"]:
            if item["key"] == "AUTO_START_ASYNC_MIGRATIONS":
                self.assertEqual(item["editable"], True)

    def test_can_retrieve_setting(self):

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["key"], "AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(json_response["value"], False)
        self.assertEqual(
            json_response["description"],
            "Whether the earliest unapplied async migration should be triggered automatically on server startup",
        )
        self.assertEqual(json_response["value_type"], "bool")
        self.assertEqual(json_response["editable"], True)

    def test_non_staff_user_cant_list_or_retrieve(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(), self.permission_denied_response("You are not a staff user, contact your instance admin.")
        )

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(), self.permission_denied_response("You are not a staff user, contact your instance admin.")
        )

    def test_update_setting(self):
        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], False)

        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], True)

        self.assertEqual(get_instance_setting("AUTO_START_ASYNC_MIGRATIONS").value, True)
        self.assertEqual(getattr(config, "AUTO_START_ASYNC_MIGRATIONS"), True)

    def test_update_integer_setting(self):
        response = self.client.patch(
            f"/api/instance_settings/ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", {"value": 48343943943},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 48343943943)
        self.assertEqual(getattr(config, "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT"), 48343943943)

    def test_cant_update_setting_that_is_not_overridable(self):
        response = self.client.patch(f"/api/instance_settings/MATERIALIZED_COLUMNS_ENABLED", {"value": False},)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "no_api_override",
                "detail": "This setting cannot be updated from the API.",
                "attr": None,
            },
        )
        self.assertEqual(getattr(config, "MATERIALIZED_COLUMNS_ENABLED"), True)

    def test_non_staff_user_cant_update(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(), self.permission_denied_response("You are not a staff user, contact your instance admin.")
        )

        self.assertEqual(get_instance_setting("AUTO_START_ASYNC_MIGRATIONS").value, False)
        self.assertEqual(getattr(config, "AUTO_START_ASYNC_MIGRATIONS"), False)
