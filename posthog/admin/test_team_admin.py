from datetime import timedelta
from decimal import Decimal

from freezegun import freeze_time
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
            side_effect=lambda name, args=None, kwargs=None: (
                self.team_change_url if name == "admin:posthog_team_change" else self.set_api_token_url
            ),
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


@freeze_time("2026-01-01T00:00:00Z")
class TestTeamAdminLLMGateway(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = TeamAdmin(Team, AdminSite())
        self.team_change_url = f"/admin/posthog/team/{self.team.pk}/change/"

        reverse_patcher = patch(
            "posthog.admin.admins.team_admin.reverse",
            side_effect=lambda name, args=None, kwargs=None: self.team_change_url,
        )
        reverse_patcher.start()
        self.addCleanup(reverse_patcher.stop)

    def _post(self):
        request = self.factory.post("/")
        request.user = self.user
        _attach_messages(request)
        return request

    def _get(self):
        request = self.factory.get("/")
        request.user = self.user
        _attach_messages(request)
        return request

    @parameterized.expand(
        [
            ("not_enrolled", False, False, "Not enrolled"),
            ("enrolled", True, False, "Enrolled"),
            ("revoked", False, True, "Revoked"),
            ("revoked_wins_over_enabled", True, True, "Revoked"),
        ]
    )
    def test_admit_state(self, _name: str, enabled: bool, revoked: bool, expected: str) -> None:
        from django.utils import timezone

        now = timezone.now()
        self.team.llm_gateway_enabled_at = now if enabled else None
        self.team.llm_gateway_revoked_at = now if revoked else None
        self.team.save()
        rendered = str(self.admin.admit_state(self.team))
        assert expected in rendered

    def test_enable_view_sets_timestamp_and_saves(self) -> None:
        assert self.team.llm_gateway_enabled_at is None
        response = self.admin.enable_ai_gateway_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_enabled_at is not None

    def test_enable_view_is_idempotent(self) -> None:
        from django.utils import timezone

        original = timezone.now() - timedelta(days=1)
        self.team.llm_gateway_enabled_at = original
        self.team.save()
        response = self.admin.enable_ai_gateway_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_enabled_at == original

    def test_revoke_view_sets_timestamp(self) -> None:
        assert self.team.llm_gateway_revoked_at is None
        response = self.admin.revoke_ai_gateway_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_revoked_at is not None

    def test_revoke_view_is_idempotent(self) -> None:
        from django.utils import timezone

        original = timezone.now() - timedelta(days=1)
        self.team.llm_gateway_revoked_at = original
        self.team.save()
        response = self.admin.revoke_ai_gateway_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_revoked_at == original

    def test_clear_revoke_view_clears_timestamp(self) -> None:
        from django.utils import timezone

        self.team.llm_gateway_revoked_at = timezone.now()
        self.team.save()
        response = self.admin.clear_ai_gateway_revoke_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_revoked_at is None

    def test_clear_revoke_view_no_op_when_already_null(self) -> None:
        assert self.team.llm_gateway_revoked_at is None
        response = self.admin.clear_ai_gateway_revoke_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        self.team.refresh_from_db()
        assert self.team.llm_gateway_revoked_at is None

    @parameterized.expand(
        [
            ("enable_first_time", "enable_ai_gateway_view", "llm_gateway_enabled_at", False),
            ("enable_already_enabled", "enable_ai_gateway_view", "llm_gateway_enabled_at", True),
            ("revoke_first_time", "revoke_ai_gateway_view", "llm_gateway_revoked_at", False),
            ("revoke_already_revoked", "revoke_ai_gateway_view", "llm_gateway_revoked_at", True),
            ("clear_revoke_with_revoke", "clear_ai_gateway_revoke_view", "llm_gateway_revoked_at", True),
            ("clear_revoke_no_op", "clear_ai_gateway_revoke_view", "llm_gateway_revoked_at", False),
        ]
    )
    def test_views_refresh_policy_cache(self, _name: str, view_name: str, field: str, preset_already: bool) -> None:
        from django.utils import timezone

        if preset_already:
            setattr(self.team, field, timezone.now() - timedelta(days=1))
            self.team.save()

        with patch("posthog.storage.team_llm_gateway_policy_cache.update_team_llm_gateway_policy_cache") as mock_update:
            response = getattr(self.admin, view_name)(self._post(), str(self.team.pk))

        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        # Refresh fires on every click, including no-op clicks where team.save()
        # is skipped and the Team.save signal therefore never runs.
        assert mock_update.call_count == 1
        assert mock_update.call_args.args[0].pk == self.team.pk

    @parameterized.expand(
        [
            ("enable", "enable_ai_gateway_view"),
            ("revoke", "revoke_ai_gateway_view"),
            ("clear_revoke", "clear_ai_gateway_revoke_view"),
        ]
    )
    def test_views_reject_non_post(self, _name: str, view_name: str) -> None:
        response = getattr(self.admin, view_name)(self._get(), str(self.team.pk))
        assert response.status_code == 405
        self.team.refresh_from_db()
        assert self.team.llm_gateway_enabled_at is None
        assert self.team.llm_gateway_revoked_at is None

    @parameterized.expand(
        [
            ("enable", "enable_ai_gateway_view"),
            ("revoke", "revoke_ai_gateway_view"),
            ("clear_revoke", "clear_ai_gateway_revoke_view"),
        ]
    )
    def test_views_require_change_permission(self, _name: str, view_name: str) -> None:
        with patch.object(self.admin, "has_change_permission", return_value=False):
            with self.assertRaises(PermissionDenied):
                getattr(self.admin, view_name)(self._post(), str(self.team.pk))

    def test_policy_cache_blob_absent(self) -> None:
        with patch(
            "posthog.storage.team_llm_gateway_policy_cache.get_team_llm_gateway_policy_from_redis",
            return_value=(None, "absent"),
        ):
            rendered = str(self.admin.policy_cache_blob(self.team))
        assert "no entry in Redis" in rendered

    def test_policy_cache_blob_negative_sentinel(self) -> None:
        with patch(
            "posthog.storage.team_llm_gateway_policy_cache.get_team_llm_gateway_policy_from_redis",
            return_value=(None, "redis_negative"),
        ):
            rendered = str(self.admin.policy_cache_blob(self.team))
        assert "negative-cache sentinel" in rendered
        assert "default-deny" in rendered

    def test_policy_cache_blob_renders_blob(self) -> None:
        with patch(
            "posthog.storage.team_llm_gateway_policy_cache.get_team_llm_gateway_policy_from_redis",
            return_value=(
                {"id": self.team.id, "llm_gateway_enabled_at": "2026-06-02T00:00:00+00:00"},
                "redis_hit",
            ),
        ):
            rendered = str(self.admin.policy_cache_blob(self.team))
        assert "llm_gateway_enabled_at" in rendered

    def test_policy_cache_blob_escapes_html_in_values(self) -> None:
        # api_token is settable by staff via set_api_token_view, so the
        # cache projection can carry HTML/JS that must not render raw.
        with patch(
            "posthog.storage.team_llm_gateway_policy_cache.get_team_llm_gateway_policy_from_redis",
            return_value=(
                {"id": self.team.id, "api_token": "<script>alert(1)</script>"},
                "redis_hit",
            ),
        ):
            rendered = str(self.admin.policy_cache_blob(self.team))
        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered


class TestTeamAdminFormOverspendAllowance(BaseTest):
    def _form(self, value, instance=None):
        instance = instance or self.team
        request = RequestFactory().get("/")
        request.user = self.user
        form_class = TeamAdmin(Team, AdminSite()).get_form(request, instance)
        form = form_class(instance=instance)
        form.cleaned_data = {"llm_gateway_overspend_allowance_usd": value}
        return form

    @parameterized.expand([("whole", Decimal("5"), Decimal("5.000000")), ("none_passthrough", None, None)])
    def test_clean_accepts_valid(self, _name, value, expected) -> None:
        self.assertEqual(self._form(value).clean_llm_gateway_overspend_allowance_usd(), expected)

    @parameterized.expand(
        [("negative", Decimal("-1")), ("over_max", Decimal("10001")), ("too_precise", Decimal("1.0000001"))]
    )
    def test_clean_rejects_invalid(self, _name, value) -> None:
        from django.forms import ValidationError

        with self.assertRaises(ValidationError):
            self._form(value).clean_llm_gateway_overspend_allowance_usd()

    def test_clean_rejects_child_environment(self) -> None:
        from django.forms import ValidationError

        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        with self.assertRaises(ValidationError):
            self._form(Decimal("5"), instance=child).clean_llm_gateway_overspend_allowance_usd()
