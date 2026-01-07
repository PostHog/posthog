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
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()

        assert json_response["count"] == len(CONSTANCE_CONFIG)

        # Check an editable attribute
        for item in json_response["results"]:
            if item["key"] == "AUTO_START_ASYNC_MIGRATIONS":
                assert item["editable"]

            if item["key"] == "EMAIL_HOST_PASSWORD":
                assert item["is_secret"]
                assert item["value"] == ""

    def test_can_retrieve_setting(self):
        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()

        assert json_response["key"] == "AUTO_START_ASYNC_MIGRATIONS"
        assert not json_response["value"]
        assert json_response["description"] == "Whether the earliest unapplied async migration should be triggered automatically on server startup."
        assert json_response["value_type"] == "bool"
        assert json_response["editable"]

    def test_retrieve_secret_setting(self):
        response = self.client.get(f"/api/instance_settings/EMAIL_HOST_PASSWORD")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()

        assert json_response["key"] == "EMAIL_HOST_PASSWORD"
        assert json_response["value"] == ""  # empty values are returned
        assert json_response["editable"]
        assert json_response["is_secret"]

        # When a value is set, the value is never exposed again
        with override_instance_config("EMAIL_HOST_PASSWORD", "this_is_a_secret_sssshhh"):
            response = self.client.get(f"/api/instance_settings/EMAIL_HOST_PASSWORD")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()

        assert json_response["key"] == "EMAIL_HOST_PASSWORD"
        assert json_response["value"] == "*****"  # note redacted value
        assert json_response["is_secret"]

    def test_non_staff_user_cant_list_or_retrieve(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You are not a staff user, contact your instance admin.")

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You are not a staff user, contact your instance admin.")

    def test_update_setting(self):
        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS")
        assert response.status_code == status.HTTP_200_OK
        assert not response.json()["value"]

        response = self.client.patch(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"]

        assert get_instance_setting_helper("AUTO_START_ASYNC_MIGRATIONS").value
        assert get_instance_setting("AUTO_START_ASYNC_MIGRATIONS")

    def test_updating_email_settings(self):
        set_instance_setting("EMAIL_HOST", "localhost")
        with self.settings(SITE_URL="http://localhost:8000", CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.patch(
                f"/api/instance_settings/EMAIL_DEFAULT_FROM",
                {"value": "hellohello@posthog.com"},
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"] == "hellohello@posthog.com"

        assert mail.outbox[0].from_email == "hellohello@posthog.com"
        assert mail.outbox[0].subject == "This is a test email of your PostHog instance"
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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"] == 48343943943
        assert get_instance_setting("ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT") == 48343943943

    def test_cant_update_setting_that_is_not_overridable(self):
        response = self.client.patch(f"/api/instance_settings/MATERIALIZED_COLUMNS_ENABLED", {"value": False})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"type": "validation_error", "code": "no_api_override", "detail": "This setting cannot be updated from the API.", "attr": None}
        assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")

    def test_non_staff_user_cant_update(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/instance_settings/AUTO_START_ASYNC_MIGRATIONS", {"value": True})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You are not a staff user, contact your instance admin.")

        assert not get_instance_setting_helper("AUTO_START_ASYNC_MIGRATIONS").value
        assert not get_instance_setting("AUTO_START_ASYNC_MIGRATIONS")
