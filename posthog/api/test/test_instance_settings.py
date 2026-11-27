import json

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.instance_settings import (
    InstanceSettingHelper,
    InstanceSettingsSerializer,
    cast_str_to_desired_type,
    get_instance_setting as get_instance_setting_helper,
)
from posthog.models import ActivityLog
from posthog.models.instance_setting import get_instance_setting, set_instance_setting
from posthog.settings import CONSTANCE_CONFIG


class TestCastStrToDesiredType(unittest.TestCase):
    @parameterized.expand(
        [
            # int
            ("int_from_str", "42", int, 42),
            ("int_from_int", 42, int, 42),
            # bool
            ("bool_true", "true", bool, True),
            ("bool_false", "false", bool, False),
            # str passthrough
            ("str_passthrough", "hello", str, "hello"),
            # list[int] — all accepted input formats
            ("list_from_list", [1, 2, 3], list[int], [1, 2, 3]),
            ("list_from_csv", "4, 5, 6", list[int], [4, 5, 6]),
            ("list_from_json_str", "[7, 8, 9]", list[int], [7, 8, 9]),
            ("list_empty_str", "", list[int], []),
            ("list_empty_list", [], list[int], []),
        ]
    )
    def test_cast_success(self, _name: str, value: object, target_type: type, expected: object) -> None:
        self.assertEqual(cast_str_to_desired_type(value, target_type), expected)

    @parameterized.expand(
        [
            ("list_non_int_items", "1, two, 3", list[int]),
            ("list_invalid_json", "[1, 2", list[int]),
            ("list_non_json_non_list_type", 999, list[int]),
        ]
    )
    def test_cast_raises_on_bad_input(self, _name: str, value: object, target_type: type) -> None:
        with self.assertRaises((ValueError, TypeError)):
            cast_str_to_desired_type(value, target_type)


class TestNoSecretInstanceSettings(unittest.TestCase):
    SENSITIVE_NAME_SUBSTRINGS = ("SECRET", "PASSWORD", "KEY", "TOKEN")

    def test_no_instance_setting_is_named_like_a_credential(self) -> None:
        offenders = [key for key in CONSTANCE_CONFIG if any(s in key for s in self.SENSITIVE_NAME_SUBSTRINGS)]
        self.assertEqual(
            offenders,
            [],
            f"Instance settings are stored in plain text and editable by any staff user. Make {offenders} "
            f"an environment variable in posthog/settings/ instead, or rename them if they are not secrets.",
        )


class TestListSettingValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "", True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "2", True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", " 2, 44 ,123 ", True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "2;44", False),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "team 2", False),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", [2], False),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", ",".join(["1234567"] * 128), False),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", "", True),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", " 0123456789abcdef , fedcba9876543210 ", True),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", ",".join([f"{i:016x}" for i in range(60)]), True),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", ",".join([f"{i:016x}" for i in range(61)]), False),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", "0123456789abcdef" * 4, False),
            ("TRENDS_RANKED_BREAKDOWN_QUERY_SIGNATURES", "0123456789ABCDEF", False),
        ]
    )
    def test_list_settings_accept_only_storable_comma_separated_values(
        self, key: str, value: object, valid: bool
    ) -> None:
        serializer = InstanceSettingsSerializer(
            instance=InstanceSettingHelper(key=key),
            data={"value": value},
            partial=True,
        )
        self.assertEqual(serializer.is_valid(), valid, serializer.errors)


class TestInstanceSettings(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _instance_setting_logs(self):
        return ActivityLog.objects.filter(scope="InstanceSetting")

    def _clear_user_org(self):
        self.user.current_organization = None
        self.user.current_team = None
        self.user.save(update_fields=["current_organization", "current_team"])

    def test_list_instance_settings(self):
        response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["count"], len(CONSTANCE_CONFIG))

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
            "Whether the earliest unapplied async migration should be triggered automatically on server startup.",
        )
        self.assertEqual(json_response["value_type"], "bool")
        self.assertEqual(json_response["editable"], True)

    def test_non_staff_user_cant_list_or_retrieve(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You are not a staff user, contact your instance admin."),
        )

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You are not a staff user, contact your instance admin."),
        )

    @parameterized.expand(
        [
            ("AUTO_START_ASYNC_MIGRATIONS", False, True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "", "2"),
        ]
    )
    def test_update_setting(self, key: str, before: object, after: object) -> None:
        response = self.client.get(f"/api/instance_settings/{key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], before)

        response = self.client.patch(f"/api/instance_settings/{key}", {"value": after}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], after)

        self.assertEqual(get_instance_setting_helper(key).value, after)
        self.assertEqual(get_instance_setting(key), after)

    def test_update_integer_setting(self):
        response = self.client.patch(
            f"/api/instance_settings/GROWTH_ICP_REENRICH_DAILY_CAP",
            {"value": 48343943943},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 48343943943)
        self.assertEqual(get_instance_setting("GROWTH_ICP_REENRICH_DAILY_CAP"), 48343943943)

    def test_update_list_int_setting(self):
        valid_cases = [
            ("json_array", [1, 2, 3], [1, 2, 3]),
            ("comma_separated", "4, 5, 6", [4, 5, 6]),
            ("json_string", "[7, 8, 9]", [7, 8, 9]),
            ("empty_string", "", []),
            (
                "indented_json_string_that_fits_once_stored",
                json.dumps(list(range(100000, 100100)), indent=2),
                list(range(100000, 100100)),
            ),
        ]
        for name, input_value, expected in valid_cases:
            with self.subTest(name):
                response = self.client.patch(
                    "/api/instance_settings/CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS",
                    {"value": input_value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.json()["value"], expected)

        invalid_cases = [
            ("non_int_items", "1, two, 3"),
            ("invalid_json", "[1, 2"),
            ("comma_string_too_long_once_stored", ",".join(["1"] * 511)),
        ]
        for name, input_value in invalid_cases:
            with self.subTest(name):
                response = self.client.patch(
                    "/api/instance_settings/CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS",
                    {"value": input_value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cant_update_setting_that_is_not_overridable(self):
        response = self.client.patch(f"/api/instance_settings/MATERIALIZED_COLUMNS_ENABLED", {"value": False})
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
        self.assertEqual(get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"), True)

    @parameterized.expand(
        [
            ("AUTO_START_ASYNC_MIGRATIONS", False, True),
            ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", "", "2"),
        ]
    )
    def test_non_staff_user_cant_update(self, key: str, before: object, after: object) -> None:
        self.user.is_staff = False
        self.user.save()

        response = self.client.patch(f"/api/instance_settings/{key}", {"value": after}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You are not a staff user, contact your instance admin."),
        )

        self.assertEqual(get_instance_setting_helper(key).value, before)
        self.assertEqual(get_instance_setting(key), before)

    @parameterized.expand(
        [
            ("bool", "AUTO_START_ASYNC_MIGRATIONS", False, True),
            ("int", "GROWTH_ICP_REENRICH_DAILY_CAP", 500, 600),
            ("string", "CLICKHOUSE_KILL_SWITCH", "off", "light"),
        ]
    )
    def test_update_setting_writes_activity_log(
        self,
        _name: str,
        key: str,
        before: object,
        after: object,
    ):
        set_instance_setting(key, before)
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/{key}", {"value": after})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logs = self._instance_setting_logs()
        self.assertEqual(logs.count(), initial_count + 1)

        log = logs.order_by("-created_at").first()
        assert log is not None
        self.assertEqual(log.scope, "InstanceSetting")
        self.assertEqual(log.item_id, key)
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertIsNone(log.team_id)
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.was_impersonated)

        assert log.detail is not None
        self.assertEqual(log.detail["name"], key)
        changes = log.detail["changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "InstanceSetting")
        self.assertEqual(changes[0]["field"], key)
        self.assertEqual(changes[0]["action"], "changed")
        self.assertEqual(changes[0]["before"], before)
        self.assertEqual(changes[0]["after"], after)

    @parameterized.expand(
        [
            ("bool", "AUTO_START_ASYNC_MIGRATIONS", True),
            ("int", "GROWTH_ICP_REENRICH_DAILY_CAP", 500),
            ("string", "CLICKHOUSE_KILL_SWITCH", "off"),
        ]
    )
    def test_no_op_update_does_not_log(self, _name: str, key: str, value: object):
        set_instance_setting(key, value)
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/{key}", {"value": value})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(self._instance_setting_logs().count(), initial_count)

    def test_failed_update_does_not_log(self):
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/MATERIALIZED_COLUMNS_ENABLED", {"value": False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(self._instance_setting_logs().count(), initial_count)

    @patch("posthog.api.instance_settings.is_impersonated", return_value=True)
    def test_update_logs_impersonation(self, _mock_is_impersonated):
        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = self._instance_setting_logs().order_by("-created_at").first()
        assert log is not None
        self.assertTrue(log.was_impersonated)

    def test_update_logs_with_first_organization_when_current_org_unset(self):
        membership = self.user.organization_memberships.first()
        assert membership is not None
        membership_org_id = membership.organization_id
        self._clear_user_org()
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logs = self._instance_setting_logs()
        self.assertEqual(logs.count(), initial_count + 1)

        log = logs.order_by("-created_at").first()
        assert log is not None
        self.assertEqual(log.organization_id, membership_org_id)

    def test_update_with_no_organization_does_not_log(self):
        self._clear_user_org()
        self.user.organization_memberships.all().delete()
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The setting itself must still be persisted; only the audit row is skipped.
        self.assertEqual(get_instance_setting("AUTO_START_ASYNC_MIGRATIONS"), True)
        self.assertEqual(self._instance_setting_logs().count(), initial_count)
