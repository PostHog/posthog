from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin.exceptions import AlreadyRegistered
from django.test import Client, override_settings

from posthog.admin import register_all_admin
from posthog.models.team.team import Team


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestTeamAdminSetApiTokenView(BaseTest):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not admin.site.is_registered(Team):
            try:
                register_all_admin()
            except AlreadyRegistered:
                pass

    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.team.api_token = "phc_admin_test_old"
        self.team.save()
        self.client = Client()
        self.client.force_login(self.user)
        self.url = f"/admin/posthog/team/{self.team.pk}/set-api-token/"

    def test_get_renders_form_with_current_token(self) -> None:
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b"phc_admin_test_old" in response.content
        assert b'name="new_token"' in response.content

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_post_with_valid_token_invokes_model_method_and_redirects(self, _mock_set_cache, _mock_push_vercel) -> None:
        response = self.client.post(self.url, {"new_token": "phc_admin_test_new"})

        assert response.status_code == 302
        assert response["Location"] == f"/admin/posthog/team/{self.team.pk}/change/"

        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_new"

    def test_post_with_empty_token_shows_error_and_does_not_change_token(self) -> None:
        response = self.client.post(self.url, {"new_token": "   "})

        assert response.status_code == 302
        assert response["Location"] == self.url
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_old"

    def test_post_with_identical_token_shows_error_and_does_not_change_token(self) -> None:
        response = self.client.post(self.url, {"new_token": "phc_admin_test_old"})

        assert response.status_code == 302
        assert response["Location"] == self.url
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_old"

    def test_post_with_duplicate_token_shows_error_and_does_not_change_token(self) -> None:
        from posthog.models.team.team import Team

        Team.objects.create(organization=self.organization, api_token="phc_duplicate")

        response = self.client.post(self.url, {"new_token": "phc_duplicate"})

        assert response.status_code == 302
        assert response["Location"] == self.url
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_old"
