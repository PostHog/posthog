from decimal import Decimal

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.forms import ModelForm
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.inlines.team_inline import TeamInline
from posthog.llm.gateway_internal_client import CreditResult
from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.ai_gateway.backend.facade.api import add_team_credit


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


@time_machine.travel("2026-01-01T00:00:00Z", tick=False)
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
        # api_token is settable by staff through the console Set API token operation, so the
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


class TestTeamAdminAIGatewayWallet(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = TeamAdmin(Team, AdminSite())
        self.credit_url = f"/admin/posthog/team/{self.team.pk}/add-ai-gateway-credit/"
        self.team_change_url = f"/admin/posthog/team/{self.team.pk}/change/"

        reverse_patcher = patch(
            "posthog.admin.admins.team_admin.reverse",
            side_effect=lambda name, args=None, kwargs=None: (
                self.team_change_url if name == "admin:posthog_team_change" else self.credit_url
            ),
        )
        reverse_patcher.start()
        self.addCleanup(reverse_patcher.stop)

    def _get(self):
        request = self.factory.get("/")
        request.user = self.user
        _attach_messages(request)
        return request

    @parameterized.expand([("direct", False, ""), ("impersonated", True, "(impersonated)")])
    def test_credit_history_renders_recorded_top_ups(self, _name: str, impersonated: bool, marker: str) -> None:
        result = CreditResult(
            team_id=self.team.id, entry_id="e1", amount_usd="25.000000", balance_usd="35.000000", duplicate=False
        )
        with patch("posthog.llm.gateway_internal_client.add_credit", return_value=result):
            add_team_credit(
                self.team.pk,
                Decimal("25.00"),
                "goodwill",
                form_nonce="n1",
                actor=self.user,
                was_impersonated=impersonated,
            )

        rendered = str(self.admin.ai_gateway_credit_history(self.team))
        assert self.user.email in rendered
        assert "25.000000" in rendered
        assert "goodwill" in rendered
        assert marker in rendered

    def test_credit_history_empty_state(self) -> None:
        rendered = str(self.admin.ai_gateway_credit_history(self.team))
        assert "no top-ups recorded" in rendered

    def test_credit_history_scoped_to_team(self) -> None:
        # Another team's top-ups must not render on this team's page.
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        ActivityLog.objects.create(
            organization_id=other_team.organization_id,
            team_id=other_team.id,
            scope="AIGatewayCredit",
            activity="credit_added",
            item_id="other-1",
            detail={"context": {"amount_usd": "99", "reason": "other-team-secret", "balance_usd": "99"}},
        )
        rendered = str(self.admin.ai_gateway_credit_history(self.team))
        assert "other-team-secret" not in rendered
        assert "no top-ups recorded" in rendered


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


class TestTeamInlineForm(BaseTest):
    def _inline_form(self, data: dict | None = None) -> ModelForm:
        request = RequestFactory().get("/")
        request.user = self.user
        form_class = TeamInline(Organization, AdminSite()).get_formset(request).form
        return form_class(data=data, instance=self.team) if data is not None else form_class()

    def test_test_account_filters_is_not_required(self) -> None:
        # Guards org-disable: the field must stay optional or an empty [] re-blocks the org save.
        assert self._inline_form().fields["test_account_filters"].required is False

    def test_blank_test_account_filters_normalizes_to_empty_list(self) -> None:
        # Blank input cleans to None; it must normalize to [] so it never hits the NOT NULL column as None.
        form = self._inline_form({"test_account_filters": ""})
        form.is_valid()  # only this field's outcome matters; other inline fields are absent
        assert "test_account_filters" not in form.errors
        assert form.cleaned_data["test_account_filters"] == []

    @parameterized.expand([("object", "{}"), ("nested_object", '{"key": "email"}'), ("string", '"oops"')])
    def test_non_list_test_account_filters_is_rejected(self, _name: str, raw: str) -> None:
        # required=False must not let non-list JSON through onto the field.
        form = self._inline_form({"test_account_filters": raw})
        form.is_valid()
        assert "test_account_filters" in form.errors
