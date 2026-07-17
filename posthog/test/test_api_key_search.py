from posthog.test.base import BaseTest

from django.test import Client, override_settings

from parameterized import parameterized

from posthog.models.utils import generate_random_token_secret
from posthog.test.api_keys import create_project_secret_api_key


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestApiKeySearchView(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)
        self.user.is_staff = True
        self.user.save()

    def _search(self, query: str):
        return self.client.post("/admin/apikeysearch", data={"q": query})

    def test_requires_staff(self):
        self.user.is_staff = False
        self.user.save()

        response = self._search("phx_whatever")

        self.assertEqual(response.status_code, 302)

    def test_get_renders_search_form(self):
        response = self.client.get("/admin/apikeysearch")

        self.assertEqual(response.status_code, 200)

    def test_finds_project_secret_api_key(self):
        key, value = create_project_secret_api_key(team=self.team, created_by=self.user, label="PSAK Search Key")

        response = self._search(value)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"PSAK Search Key", response.content)
        self.assertIn(f"/admin/posthog/projectsecretapikey/{key.id}/change/".encode(), response.content)

    @parameterized.expand(
        [
            ("primary", "secret_api_token", b"Feature Flags Secure API Key"),
            ("backup", "secret_api_token_backup", b"(Backup)"),
        ]
    )
    def test_finds_legacy_team_secret_token(self, _name: str, token_field: str, expected_content: bytes):
        token = generate_random_token_secret()
        setattr(self.team, token_field, token)
        self.team.save()

        response = self._search(token)

        self.assertEqual(response.status_code, 200)
        self.assertIn(expected_content, response.content)
        self.assertIn(self.team.name.encode(), response.content)

    def test_unknown_token_shows_no_results(self):
        response = self._search("not-a-real-key-at-all-1234567890")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No results found", response.content)
