from posthog.test.base import BaseTest

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
        self.change_url = f"/admin/posthog/projectsecretapikey/{self.key.pk}/change/"

    def test_change_page_points_the_roll_action_to_the_console(self):
        response = self.client.get(self.change_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/admin/console/teams/{self.team.pk}/#panel-secret-api-keys".encode(), response.content)

    def test_add_page_is_disabled(self):
        response = self.client.get("/admin/posthog/projectsecretapikey/add/")

        self.assertEqual(response.status_code, 403)
