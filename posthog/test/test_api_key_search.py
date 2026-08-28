from posthog.test.base import BaseTest

from django.test import Client, override_settings

from parameterized import parameterized

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import LEGACY_PERSONAL_API_KEY_SALT
from posthog.models.utils import (
    generate_random_token,
    generate_random_token_personal,
    generate_random_token_secret,
    hash_key_value,
    mask_key_value,
)
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

    def _create_personal_api_key(self, token: str, mode: str = "sha256", iterations: int | None = None):
        if mode == "sha256":
            secure_value = hash_key_value(token)
        else:
            secure_value = hash_key_value(
                token, mode="pbkdf2", legacy_salt=LEGACY_PERSONAL_API_KEY_SALT, iterations=iterations
            )
        return PersonalAPIKey.objects.create(
            user=self.user,
            label="Searched Key",
            secure_value=secure_value,
            mask_value=mask_key_value(token),
            scopes=["*"],
        )

    def test_requires_staff(self):
        self.user.is_staff = False
        self.user.save()

        response = self._search("phx_whatever")

        self.assertEqual(response.status_code, 302)

    def test_get_renders_search_form(self):
        response = self.client.get("/admin/apikeysearch")

        self.assertEqual(response.status_code, 200)

    @parameterized.expand(
        [
            ("modern_phx_sha256", True, "sha256", None),
            ("legacy_unprefixed_sha256", False, "sha256", None),
            ("legacy_unprefixed_pbkdf2_260000", False, "pbkdf2", 260000),
            ("legacy_unprefixed_pbkdf2_390000", False, "pbkdf2", 390000),
        ]
    )
    def test_finds_personal_api_key(self, _name: str, prefixed: bool, mode: str, iterations: int | None):
        token = generate_random_token_personal() if prefixed else generate_random_token(32)
        self._create_personal_api_key(token, mode=mode, iterations=iterations)

        response = self._search(token)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Searched Key", response.content)
        self.assertIn(self.user.email.encode(), response.content)

    def test_strips_whitespace_from_query(self):
        token = generate_random_token_personal()
        self._create_personal_api_key(token)

        response = self._search(f"  {token}\n")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Searched Key", response.content)

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
