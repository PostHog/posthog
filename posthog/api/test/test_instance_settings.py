from posthog.test.base import APIBaseTest

from django.core import mail

from rest_framework import status

from posthog.api.instance_settings import get_instance_setting as get_instance_setting_helper
from posthog.models.instance_setting import get_instance_setting, override_instance_config, set_instance_setting
from posthog.settings import CONSTANCE_CONFIG


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
        self.assertEqual(json_response["results"][0]["key"], "RECORDINGS_TTL_WEEKS")
        self.assertEqual(json_response["results"][0]["value"], 3)
        self.assertEqual(
            json_response["results"][0]["description"],
            "Number of weeks recordings will be kept before removing them (for all projects). Storing recordings for a shorter timeframe can help reduce Clickhouse disk usage.",
        )
        self.assertEqual(json_response["results"][0]["value_type"], "int")
        self.assertEqual(json_response["results"][0]["editable"], True)

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
