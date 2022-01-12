from rest_framework import status

from posthog.settings import CONSTANCE_CONFIG, SETTINGS_ALLOWING_API_OVERRIDE
from posthog.test.base import APIBaseTest


class TestInstanceSettings(APIBaseTest):
    def setUp(self):
        self.user.is_staff = True
        self.user.save()
        return super().setUp()

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

    def test_update_setting(self):
        response = self.client.get(f"/api/instance_settings/").json()

        self.assertEqual(response["ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK"]["value"], False)

        response = self.client.post(
            f"/api/instance_settings/update_setting",
            data={"key": "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", "value": "true"},
        ).json()

        response = self.client.get(f"/api/instance_settings/").json()
        self.assertEqual(response["ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK"]["value"], True)

        from constance import config

        self.assertEqual(getattr(config, "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK"), True)

        response = self.client.post(
            f"/api/instance_settings/update_setting",
            data={"key": "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", "value": "48343943943"},
        ).json()
        self.assertEqual(getattr(config, "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT"), 48343943943)
