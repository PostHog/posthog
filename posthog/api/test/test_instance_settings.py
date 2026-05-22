import json

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core import mail

from parameterized import parameterized
from rest_framework import status

from posthog.api.instance_settings import (
    REDACTED,
    UNSET,
    _redact_if_secret,
    cast_str_to_desired_type,
    get_instance_setting as get_instance_setting_helper,
)
from posthog.models import ActivityLog
from posthog.models.instance_setting import get_instance_setting, override_instance_config, set_instance_setting
from posthog.settings import CONSTANCE_CONFIG, SECRET_SETTINGS, SETTINGS_ALLOWING_API_OVERRIDE


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


class TestSecretSettingsCoverage(unittest.TestCase):
    SENSITIVE_NAME_SUBSTRINGS = ("SECRET", "PASSWORD", "KEY", "TOKEN")

    def test_api_overridable_keys_with_sensitive_names_are_in_secret_settings(self) -> None:
        offenders = [
            key
            for key in SETTINGS_ALLOWING_API_OVERRIDE
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

    @parameterized.expand(
        [
            ("none", None, UNSET),
            ("empty_string", "", UNSET),
            ("nonempty_string", "hunter2", REDACTED),
            ("integer", 42, REDACTED),
            ("boolean", False, REDACTED),
        ]
    )
    def test_redact_if_secret_redacts_secret_keys(self, _name: str, value: object, expected: object) -> None:
        self.assertEqual(_redact_if_secret("EMAIL_HOST_PASSWORD", value), expected)

    @parameterized.expand(
        [
            ("string", "smtp.example.com"),
            ("integer", 25),
            ("boolean_true", True),
            ("boolean_false", False),
            ("empty_string", ""),
            ("none", None),
            ("list", [1, 2, 3]),
        ]
    )
    def test_redact_if_secret_passes_through_non_secret_keys(self, _name: str, value: object) -> None:
        self.assertEqual(_redact_if_secret("EMAIL_HOST", value), value)


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

            if item["key"] == "EMAIL_HOST_PASSWORD":
                self.assertEqual(item["is_secret"], True)
                self.assertEqual(item["value"], "")

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

    def test_retrieve_secret_setting(self):
        response = self.client.get(f"/api/instance_settings/EMAIL_HOST_PASSWORD")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["key"], "EMAIL_HOST_PASSWORD")
        self.assertEqual(json_response["value"], "")  # empty values are returned
        self.assertEqual(json_response["editable"], True)
        self.assertEqual(json_response["is_secret"], True)

        # When a value is set, the value is never exposed again
        with override_instance_config("EMAIL_HOST_PASSWORD", "this_is_a_secret_sssshhh"):
            response = self.client.get(f"/api/instance_settings/EMAIL_HOST_PASSWORD")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()

        self.assertEqual(json_response["key"], "EMAIL_HOST_PASSWORD")
        self.assertEqual(json_response["value"], "*****")  # note redacted value
        self.assertEqual(json_response["is_secret"], True)

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

    def test_update_setting(self):
        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], False)

        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], True)

        self.assertEqual(get_instance_setting_helper("AUTO_START_ASYNC_MIGRATIONS").value, True)
        self.assertEqual(get_instance_setting("AUTO_START_ASYNC_MIGRATIONS"), True)

    def test_updating_email_settings(self):
        set_instance_setting("EMAIL_HOST", "localhost")
        with self.settings(SITE_URL="http://localhost:8000", CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.patch(
                f"/api/instance_settings/EMAIL_DEFAULT_FROM",
                {"value": "hellohello@posthog.com"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], "hellohello@posthog.com")

        self.assertEqual(mail.outbox[0].from_email, "hellohello@posthog.com")
        self.assertEqual(mail.outbox[0].subject, "This is a test email of your PostHog instance")
        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message,
            "http://localhost:8000",
            preheader="Email successfully set up!",
        )

    def test_update_integer_setting(self):
        response = self.client.patch(
            f"/api/instance_settings/ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
            {"value": 48343943943},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 48343943943)
        self.assertEqual(get_instance_setting("ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT"), 48343943943)

    def test_update_list_int_setting(self):
        valid_cases = [
            ("json_array", [1, 2, 3], [1, 2, 3]),
            ("comma_separated", "4, 5, 6", [4, 5, 6]),
            ("json_string", "[7, 8, 9]", [7, 8, 9]),
            ("empty_string", "", []),
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

    def test_non_staff_user_cant_update(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You are not a staff user, contact your instance admin."),
        )

        self.assertEqual(get_instance_setting_helper("AUTO_START_ASYNC_MIGRATIONS").value, False)
        self.assertEqual(get_instance_setting("AUTO_START_ASYNC_MIGRATIONS"), False)

    @parameterized.expand(
        [
            ("bool", "AUTO_START_ASYNC_MIGRATIONS", False, True),
            ("int", "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", 30, 60),
            ("string", "GITHUB_APP_SLUG", "", "posthog-app"),
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
            ("install", "", "hunter2", "<unset>", "<redacted>"),
            ("rotate", "old_secret", "new_secret", "<redacted>", "<redacted>"),
            ("clear", "old_secret", "", "<redacted>", "<unset>"),
        ]
    )
    def test_update_secret_setting_redacts_value(
        self,
        _name: str,
        before: str,
        after: str,
        expected_before: str,
        expected_after: str,
    ):
        set_instance_setting("EMAIL_HOST_PASSWORD", before)
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/EMAIL_HOST_PASSWORD", {"value": after})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logs = self._instance_setting_logs()
        self.assertEqual(logs.count(), initial_count + 1)

        log = logs.order_by("-created_at").first()
        assert log is not None
        change = log.detail["changes"][0]
        self.assertEqual(change["before"], expected_before)
        self.assertEqual(change["after"], expected_after)

        # Defense in depth: the cleartext must appear nowhere in the serialized row.
        raw_detail = json.dumps(log.detail)
        if before:
            self.assertNotIn(before, raw_detail)
        if after:
            self.assertNotIn(after, raw_detail)

    @parameterized.expand([(key,) for key in SECRET_SETTINGS])
    def test_every_secret_setting_is_redacted_on_update(self, key: str):
        # End-to-end: PATCH every declared secret setting and assert the cleartext
        # never lands in `posthog_activitylog.detail`. Catches the case where someone
        # adds a new key to SECRET_SETTINGS but the redaction path silently misses it.
        before_value = f"old-{key}-cleartext"
        after_value = f"new-{key}-cleartext"
        set_instance_setting(key, before_value)
        initial_count = self._instance_setting_logs().count()

        response = self.client.patch(f"/api/instance_settings/{key}", {"value": after_value})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        logs = self._instance_setting_logs()
        self.assertEqual(logs.count(), initial_count + 1)

        log = logs.order_by("-created_at").first()
        assert log is not None
        change = log.detail["changes"][0]
        self.assertEqual(change["before"], "<redacted>")
        self.assertEqual(change["after"], "<redacted>")

        raw_detail = json.dumps(log.detail)
        self.assertNotIn(before_value, raw_detail)
        self.assertNotIn(after_value, raw_detail)

    @parameterized.expand([(key,) for key in SECRET_SETTINGS])
    def test_every_secret_setting_is_redacted_on_retrieve(self, key: str):
        # GET every declared secret. When set, the cleartext must never appear in the
        # response — only the "*****" placeholder. Catches regressions where a future
        # refactor of get_instance_setting drops the masking for one (or all) keys.
        cleartext = f"cleartext-for-{key}"
        with override_instance_config(key, cleartext):
            response = self.client.get(f"/api/instance_settings/{key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        json_response = response.json()

        self.assertEqual(json_response["key"], key)
        self.assertTrue(json_response["is_secret"])
        self.assertEqual(json_response["value"], "*****")
        self.assertNotIn(cleartext, response.content.decode())

    @parameterized.expand(
        [
            ("bool", "AUTO_START_ASYNC_MIGRATIONS", True),
            ("int", "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", 30),
            ("string", "GITHUB_APP_SLUG", "posthog-app"),
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

    @patch("posthog.api.instance_settings.is_impersonated_session", return_value=True)
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
