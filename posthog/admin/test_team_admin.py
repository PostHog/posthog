from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.models.team.team import Team


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


class TestTeamAdminSetApiTokenView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.team.api_token = "phc_admin_test_old"
        self.team.save()
        self.factory = RequestFactory()
        self.admin = TeamAdmin(Team, AdminSite())
        self.set_api_token_url = f"/admin/posthog/team/{self.team.pk}/set-api-token/"
        self.team_change_url = f"/admin/posthog/team/{self.team.pk}/change/"

        reverse_patcher = patch(
            "posthog.admin.admins.team_admin.reverse",
            side_effect=lambda name, args=None, kwargs=None: self.team_change_url
            if name == "admin:posthog_team_change"
            else self.set_api_token_url,
        )
        reverse_patcher.start()
        self.addCleanup(reverse_patcher.stop)

    def test_get_renders_form_with_current_token(self) -> None:
        http_request = self.factory.get(self.set_api_token_url)
        http_request.user = self.user
        _attach_messages(http_request)

        with patch("posthog.admin.admins.team_admin.render") as mock_render:
            self.admin.set_api_token_view(http_request, str(self.team.pk))

        template = mock_render.call_args.args[1]
        context = mock_render.call_args.args[2]
        assert template == "admin/posthog/team/set_api_token_form.html"
        assert context["team"].api_token == "phc_admin_test_old"
        assert context["title"] == f"Set API token - {self.team.name}"

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_post_with_valid_token_invokes_model_method_and_redirects(self, _mock_set_cache, _mock_push_vercel) -> None:
        http_request = self.factory.post(self.set_api_token_url, {"new_token": "phc_admin_test_new"})
        http_request.user = self.user
        _attach_messages(http_request)

        response = self.admin.set_api_token_view(http_request, str(self.team.pk))

        assert response.status_code == 302
        assert response["Location"] == self.team_change_url

        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_new"

    @parameterized.expand(
        [
            ("empty_token", "   "),
            ("identical_token", "phc_admin_test_old"),
            ("duplicate_token", "phc_duplicate"),
        ]
    )
    def test_post_rejected_inputs_show_error_and_do_not_change_token(self, _name: str, new_token: str) -> None:
        if new_token == "phc_duplicate":
            Team.objects.create(organization=self.organization, api_token="phc_duplicate")

        http_request = self.factory.post(self.set_api_token_url, {"new_token": new_token})
        http_request.user = self.user
        _attach_messages(http_request)

        response = self.admin.set_api_token_view(http_request, str(self.team.pk))

        assert response.status_code == 302
        assert response["Location"] == self.set_api_token_url
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_old"

    @parameterized.expand([("get",), ("post",)])
    def test_returns_403_when_user_lacks_change_permission(self, method: str) -> None:
        if method == "post":
            http_request = self.factory.post(self.set_api_token_url, {"new_token": "phc_admin_test_new"})
        else:
            http_request = self.factory.get(self.set_api_token_url)
        http_request.user = self.user
        _attach_messages(http_request)

        with patch.object(self.admin, "has_change_permission", return_value=False):
            with self.assertRaises(PermissionDenied):
                self.admin.set_api_token_view(http_request, str(self.team.pk))

        self.team.refresh_from_db()
        assert self.team.api_token == "phc_admin_test_old"
