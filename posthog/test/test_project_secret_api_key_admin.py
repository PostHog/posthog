from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client, override_settings

from posthog.test.api_keys import create_project_secret_api_key


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestProjectSecretAPIKeyAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)
        self.user.is_staff = True
        self.user.save()

        self.key, _ = create_project_secret_api_key(team=self.team, created_by=self.user, label="Admin Key")
        self.roll_url = f"/admin/posthog/projectsecretapikey/{self.key.pk}/roll/"
        self.change_url = f"/admin/posthog/projectsecretapikey/{self.key.pk}/change/"

    @patch("posthog.api.project_secret_api_key.send_project_secret_api_key_exposed")
    def test_roll_rolls_key_and_notifies(self, mock_exposed: MagicMock):
        old_secure_value = self.key.secure_value
        old_mask_value = self.key.mask_value

        response = self.client.post(self.roll_url, data={"_roll_url": "https://github.com/some/leak"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.change_url)

        self.key.refresh_from_db()
        self.assertNotEqual(self.key.secure_value, old_secure_value)
        self.assertNotEqual(self.key.mask_value, old_mask_value)
        self.assertIsNotNone(self.key.last_rolled_at)

        mock_exposed.assert_called_once_with(
            self.team.id, self.key.id, old_mask_value, "This key was detected at https://github.com/some/leak."
        )

    @patch("posthog.api.project_secret_api_key.send_project_secret_api_key_exposed")
    def test_roll_requires_post(self, mock_exposed: MagicMock):
        response = self.client.get(self.roll_url)

        self.assertEqual(response.status_code, 405)
        mock_exposed.assert_not_called()

    @patch("posthog.api.project_secret_api_key.send_project_secret_api_key_exposed")
    def test_roll_requires_staff(self, mock_exposed: MagicMock):
        self.user.is_staff = False
        self.user.save()
        old_secure_value = self.key.secure_value

        response = self.client.post(self.roll_url, data={"_roll_url": ""})

        self.assertEqual(response.status_code, 302)
        self.key.refresh_from_db()
        self.assertEqual(self.key.secure_value, old_secure_value)
        mock_exposed.assert_not_called()

    def test_change_page_renders_roll_button(self):
        response = self.client.get(self.change_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.roll_url.encode(), response.content)
        self.assertIn(b"roll_key_button", response.content)

    def test_add_page_is_disabled(self):
        response = self.client.get("/admin/posthog/projectsecretapikey/add/")

        self.assertEqual(response.status_code, 403)
