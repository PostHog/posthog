import unittest
from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.instance_settings import InstanceSettingHelper, InstanceSettingsSerializer
from posthog.models import ActivityLog
from posthog.models.instance_setting import get_instance_setting, override_instance_config, set_instance_setting
from posthog.settings import CONSTANCE_CONFIG, SECRET_SETTINGS, SETTINGS_ALLOWING_API_OVERRIDE


class TestSecretSettingsCoverage(unittest.TestCase):
    SENSITIVE_NAME_SUBSTRINGS = ("SECRET", "PASSWORD", "KEY", "TOKEN")

    def test_keys_with_sensitive_names_are_in_secret_settings(self) -> None:
        offenders = [
            key
            for key in CONSTANCE_CONFIG
            if any(s in key for s in self.SENSITIVE_NAME_SUBSTRINGS) and key not in SECRET_SETTINGS
        ]
        self.assertEqual(
            offenders,
            [],
            (
                f"Keys named like credentials must be redacted. Add {offenders} to SECRET_SETTINGS "
                f"in posthog/settings/dynamic_settings.py, or rename them if they are not actually secrets."
            ),
        )

    def test_every_secret_setting_exists_in_constance_config(self) -> None:
        missing = [key for key in SECRET_SETTINGS if key not in CONSTANCE_CONFIG]
        self.assertEqual(
            missing,
            [],
            f"SECRET_SETTINGS references unknown keys {missing}; CONSTANCE_CONFIG is the source of truth.",
        )

    def test_no_editable_setting_is_secret(self) -> None:
        # Updates write before/after values to the activity log in clear text.
        self.assertEqual(set(SETTINGS_ALLOWING_API_OVERRIDE) & set(SECRET_SETTINGS), set())


class TestInstanceSettingValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "", True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", " 2, 44 ,123 ", True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "2;44", False),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", [2], False),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", ",".join(["1234567"] * 128), False),
            ("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", "4, 5, 6", True),
            ("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", "[7, 8]", True),
            ("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", "1, two, 3", False),
            ("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", "[1, 2", False),
            ("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", ",".join(["1"] * 511), False),
            ("CLICKHOUSE_KILL_SWITCH", None, False),
            ("EMAIL_HOST", "smtp.example.com", False),
            ("AUTO_START_ASYNC_MIGRATIONS", True, False),
        ]
    )
    def test_value_validation(self, key: str, value: object, valid: bool) -> None:
        serializer = InstanceSettingsSerializer(
            instance=InstanceSettingHelper(key=key), data={"value": value}, partial=True
        )
        self.assertEqual(serializer.is_valid(), valid, serializer.errors)


class TestInstanceSettings(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _instance_setting_logs(self):
        return ActivityLog.objects.filter(scope="InstanceSetting")

    def test_list_instance_settings(self):
        with override_instance_config("AUTO_START_ASYNC_MIGRATIONS", True):
            response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["count"], len(CONSTANCE_CONFIG))
        results = {item["key"]: item for item in json_response["results"]}

        self.assertEqual(results["AUTO_START_ASYNC_MIGRATIONS"]["value"], True)
        self.assertEqual(results["AUTO_START_ASYNC_MIGRATIONS"]["is_set_in_database"], True)
        self.assertEqual(results["AUTO_START_ASYNC_MIGRATIONS"]["editable"], False)
        self.assertEqual(results["CLICKHOUSE_KILL_SWITCH"]["editable"], True)
        self.assertEqual(results["EMAIL_HOST_PASSWORD"]["is_secret"], True)
        self.assertEqual(results["EMAIL_HOST_PASSWORD"]["value"], "")
        self.assertEqual(results["EMAIL_HOST_PASSWORD"]["is_set_in_database"], False)

    def test_secret_settings_are_redacted_in_list(self):
        for key in SECRET_SETTINGS:
            set_instance_setting(key, f"cleartext-for-{key}")
        response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = {item["key"]: item for item in response.json()["results"]}
        for key in SECRET_SETTINGS:
            self.assertEqual(results[key]["value"], "*****")
        self.assertNotIn("cleartext-for-", response.content.decode())

    @parameterized.expand(
        [
            ("string", "CLICKHOUSE_KILL_SWITCH", "off", "light", "light"),
            ("list_int", "CLICKHOUSE_KILL_SWITCH_FULL_TEAMS", [], "4, 5", [4, 5]),
            ("comma_string", "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "", "2,3", "2,3"),
        ]
    )
    def test_update_editable_setting_writes_value_and_activity_log(
        self, _name: str, key: str, before: object, sent: object, stored: object
    ):
        response = self.client.patch(f"/api/instance_settings/{key}", {"value": sent}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["value"], stored)
        self.assertEqual(get_instance_setting(key), stored)

        log = self._instance_setting_logs().get(item_id=key)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.detail["changes"][0]["before"], before)
        self.assertEqual(log.detail["changes"][0]["after"], stored)

    def test_no_op_update_does_not_log(self):
        response = self.client.patch(f"/api/instance_settings/CLICKHOUSE_KILL_SWITCH", {"value": "off"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._instance_setting_logs().count(), 0)

    @parameterized.expand([("AUTO_START_ASYNC_MIGRATIONS", True), ("EMAIL_HOST_PASSWORD", "hunter2")])
    def test_settings_outside_the_allowlist_cannot_be_updated(self, key: str, value: object):
        before = get_instance_setting(key)
        response = self.client.patch(f"/api/instance_settings/{key}", {"value": value}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "no_api_override")
        self.assertEqual(get_instance_setting(key), before)
        self.assertEqual(self._instance_setting_logs().count(), 0)

    @parameterized.expand([("AUTO_START_ASYNC_MIGRATIONS", True, False), ("EMAIL_HOST_PASSWORD", "hunter2", "")])
    def test_delete_stored_value_falls_back_to_default(self, key: str, stored: object, default: object):
        set_instance_setting(key, stored)

        response = self.client.delete(f"/api/instance_settings/{key}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(get_instance_setting(key), default)

        log = self._instance_setting_logs().get(item_id=key)
        self.assertEqual(log.activity, "deleted")
        self.assertNotIn("hunter2", str(log.detail))

        self.assertEqual(self.client.delete(f"/api/instance_settings/{key}").status_code, status.HTTP_404_NOT_FOUND)

    def test_non_staff_user_cant_list_update_or_delete(self):
        self.user.is_staff = False
        self.user.save()

        for response in (
            self.client.get("/api/instance_settings/"),
            self.client.patch("/api/instance_settings/CLICKHOUSE_KILL_SWITCH", {"value": "full"}),
            self.client.delete("/api/instance_settings/CLICKHOUSE_KILL_SWITCH"),
        ):
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                self.permission_denied_response("You are not a staff user, contact your instance admin."),
            )
        self.assertEqual(get_instance_setting("CLICKHOUSE_KILL_SWITCH"), "off")
