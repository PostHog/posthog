from posthog.settings import SETTINGS_ALLOWING_API_OVERRIDE
from posthog.test.base import APIBaseTest


class TestInstanceSettings(APIBaseTest):
    def setUp(self):
        self.user.is_staff = True
        self.user.save()
        return super().setUp()

    def test_list_instance_settings(self):

        response = self.client.get(f"/api/instance_settings/").json()

        self.assertEqual(len(response.items()), len(SETTINGS_ALLOWING_API_OVERRIDE))

        for setting_name in SETTINGS_ALLOWING_API_OVERRIDE:
            self.assertTrue(setting_name in response)
            self.assertTrue("value" in response[setting_name])
            self.assertTrue("description" in response[setting_name])

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
