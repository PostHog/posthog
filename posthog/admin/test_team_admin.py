from datetime import UTC, datetime
from decimal import Decimal

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.forms import ModelForm
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.inlines.team_inline import TeamInline
from posthog.llm.gateway_internal_client import (
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    CreditResult,
    LedgerEntry,
    Wallet,
)
from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team
from posthog.personhog_client.fake_client import FakePersonHogClient
from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest

from products.ai_gateway.backend.facade.api import add_team_credit
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig


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

    def test_wallet_field_renders_actions_without_fetching(self) -> None:
        with patch("posthog.admin.admins.team_admin.get_wallet") as mock_get_wallet:
            rendered = str(self.admin.ai_gateway_wallet(self.team))
        mock_get_wallet.assert_not_called()
        assert "View wallet" in rendered
        assert "Add credit" in rendered

    def test_wallet_view_not_configured_degrades_gracefully(self) -> None:
        with patch("posthog.admin.admins.team_admin.get_wallet", side_effect=AIGatewayNotConfigured()):
            with patch("posthog.admin.admins.team_admin.render") as mock_render:
                self.admin.ai_gateway_wallet_view(self._get(), str(self.team.pk))
        assert "not configured" in mock_render.call_args.args[2]["error"]

    def test_wallet_view_unavailable_degrades_gracefully(self) -> None:
        with patch("posthog.admin.admins.team_admin.get_wallet", side_effect=AIGatewayInternalError("boom")):
            with patch("posthog.admin.admins.team_admin.render") as mock_render:
                self.admin.ai_gateway_wallet_view(self._get(), str(self.team.pk))
        error = mock_render.call_args.args[2]["error"]
        assert "wallet unavailable" in error
        assert "boom" in error

    def test_wallet_view_renders_balance(self) -> None:
        wallet = Wallet(
            team_id=self.team.id,
            known=True,
            has_ledger=True,
            balance="9.500000",
            recent=[LedgerEntry("2026-06-01", "topup", "funding", "prepaid", "10.000000", "ref-1")],
        )
        with patch("posthog.admin.admins.team_admin.get_wallet", return_value=wallet):
            with patch("posthog.admin.admins.team_admin.render") as mock_render:
                self.admin.ai_gateway_wallet_view(self._get(), str(self.team.pk))
        assert mock_render.call_args.args[2]["wallet"].balance == "9.500000"

    def test_wallet_view_requires_view_permission(self) -> None:
        with patch.object(self.admin, "has_view_permission", return_value=False):
            with self.assertRaises(PermissionDenied):
                self.admin.ai_gateway_wallet_view(self._get(), str(self.team.pk))

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


class TestTeamAdminEmailSendingSuspension(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = TeamAdmin(Team, AdminSite())
        self.suspend_url = f"/admin/posthog/team/{self.team.pk}/suspend-email-sending/"
        self.team_change_url = f"/admin/posthog/team/{self.team.pk}/change/"

        reverse_patcher = patch(
            "posthog.admin.admins.team_admin.reverse",
            side_effect=lambda name, args=None, kwargs=None: (
                self.team_change_url if name == "admin:posthog_team_change" else self.suspend_url
            ),
        )
        reverse_patcher.start()
        self.addCleanup(reverse_patcher.stop)

        suspend_email_patcher = patch("posthog.admin.admins.team_admin.send_email_sending_suspended")
        unsuspend_email_patcher = patch("posthog.admin.admins.team_admin.send_email_sending_unsuspended")
        notification_patcher = patch("posthog.admin.admins.team_admin.create_notification")
        self.mock_suspend_email = suspend_email_patcher.start()
        self.mock_unsuspend_email = unsuspend_email_patcher.start()
        self.mock_notification = notification_patcher.start()
        self.addCleanup(suspend_email_patcher.stop)
        self.addCleanup(unsuspend_email_patcher.stop)
        self.addCleanup(notification_patcher.stop)

    def _post(self, data: dict | None = None):
        request = self.factory.post("/", data or {})
        request.user = self.user
        _attach_messages(request)
        return request

    def _get(self):
        request = self.factory.get("/")
        request.user = self.user
        _attach_messages(request)
        return request

    def _config(self) -> TeamWorkflowsConfig | None:
        return TeamWorkflowsConfig.objects.filter(team_id=self.team.pk).first()

    def test_get_renders_reason_form(self) -> None:
        with patch("posthog.admin.admins.team_admin.render") as mock_render:
            self.admin.suspend_email_sending_view(self._get(), str(self.team.pk))
        assert mock_render.call_args.args[1] == "admin/posthog/team/suspend_email_sending_form.html"

    def test_post_without_reason_makes_no_changes(self) -> None:
        response = self.admin.suspend_email_sending_view(self._post({"reason": "  "}), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.suspend_url
        config = self._config()
        assert config is None or config.email_sending_suspended_at is None
        self.mock_suspend_email.delay.assert_not_called()
        self.mock_notification.assert_not_called()

    def test_suspend_sets_fields_logs_activity_and_notifies(self) -> None:
        response = self.admin.suspend_email_sending_view(
            self._post({"reason": "Hard bounce rate above 5%"}), str(self.team.pk)
        )
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url

        config = self._config()
        assert config is not None
        assert config.email_sending_suspended_at is not None
        assert config.email_sending_suspension_reason == "Hard bounce rate above 5%"

        entry = ActivityLog.objects.get(scope="Team", team_id=self.team.id, activity="email_sending_suspended")
        assert entry.user == self.user
        assert (entry.detail or {}).get("context", {}).get("reason") == "Hard bounce rate above 5%"

        assert self.mock_suspend_email.delay.call_args.kwargs["team_id"] == self.team.id
        assert self.mock_suspend_email.delay.call_args.kwargs["reason"] == "Hard bounce rate above 5%"
        assert self.mock_notification.call_count == 1

    def test_suspend_drops_the_tier_to_zero_even_when_pinned(self) -> None:
        config, _ = TeamWorkflowsConfig.objects.update_or_create(
            team=self.team, defaults={"email_sending_tier": 3, "email_sending_tier_pinned": True}
        )

        response = self.admin.suspend_email_sending_view(self._post({"reason": "spam complaints"}), str(self.team.pk))
        assert response.status_code == 302

        config.refresh_from_db()
        assert config.email_sending_suspended_at is not None
        assert config.email_sending_tier == 0
        assert config.email_sending_tier_updated_at is not None

        entry = ActivityLog.objects.get(scope="Team", team_id=self.team.id, activity="email_sending_tier_changed")
        assert entry.user == self.user
        assert (entry.detail or {})["context"] == {"reason": "staff_suspension"}

    def test_suspend_is_idempotent(self) -> None:
        self.admin.suspend_email_sending_view(self._post({"reason": "first"}), str(self.team.pk))
        response = self.admin.suspend_email_sending_view(self._post({"reason": "second"}), str(self.team.pk))
        assert response.status_code == 302

        config = self._config()
        assert config is not None
        assert config.email_sending_suspension_reason == "first"
        assert self.mock_suspend_email.delay.call_count == 1
        assert ActivityLog.objects.filter(scope="Team", activity="email_sending_suspended").count() == 1

    def test_unsuspend_clears_fields_logs_activity_and_notifies(self) -> None:
        self.admin.suspend_email_sending_view(self._post({"reason": "bad rates"}), str(self.team.pk))
        self.mock_notification.reset_mock()

        response = self.admin.unsuspend_email_sending_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        assert response["Location"] == self.team_change_url

        config = self._config()
        assert config is not None
        assert config.email_sending_suspended_at is None
        assert config.email_sending_suspension_reason == ""

        assert ActivityLog.objects.filter(scope="Team", activity="email_sending_unsuspended").count() == 1
        assert self.mock_unsuspend_email.delay.call_args.kwargs["team_id"] == self.team.id
        assert self.mock_notification.call_count == 1

    def test_unsuspend_is_a_noop_when_not_suspended(self) -> None:
        response = self.admin.unsuspend_email_sending_view(self._post(), str(self.team.pk))
        assert response.status_code == 302
        self.mock_unsuspend_email.delay.assert_not_called()
        self.mock_notification.assert_not_called()
        assert not ActivityLog.objects.filter(scope="Team", activity="email_sending_unsuspended").exists()

    @parameterized.expand(
        [
            ("suspend", "suspend_email_sending_view"),
            ("unsuspend", "unsuspend_email_sending_view"),
        ]
    )
    def test_views_require_change_permission(self, _name: str, view_name: str) -> None:
        with patch.object(self.admin, "has_change_permission", return_value=False):
            with self.assertRaises(PermissionDenied):
                getattr(self.admin, view_name)(self._post({"reason": "x"}), str(self.team.pk))


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


class TestTeamAdminEditGroupTypeMappingView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = TeamAdmin(Team, AdminSite())
        self.edit_url = f"/admin/posthog/team/{self.team.pk}/group-type-mapping/0/edit/"
        self.team_change_url = f"/admin/posthog/team/{self.team.pk}/change/"

        # Sub-second component matters: the form prefills created_at, so a lossy prefill would
        # silently truncate it on every save.
        existing_created_at = datetime(2026, 1, 15, 10, 30, 0, 123000, tzinfo=UTC)

        self.fake_client = FakePersonHogClient()
        self.fake_client.add_group_type_mapping(
            project_id=self.team.project_id,
            team_id=self.team.pk,
            group_type="organization",
            group_type_index=0,
            created_at=int(existing_created_at.timestamp() * 1000),
        )
        client_patcher = patch("posthog.admin.admins.team_admin.get_personhog_client", return_value=self.fake_client)
        client_patcher.start()
        self.addCleanup(client_patcher.stop)

        reverse_patcher = patch(
            "posthog.admin.admins.team_admin.reverse",
            side_effect=lambda name, args=None, kwargs=None: (
                self.team_change_url if name == "admin:posthog_team_change" else self.edit_url
            ),
        )
        reverse_patcher.start()
        self.addCleanup(reverse_patcher.stop)

    def _post(self, created_at: str):
        http_request = self.factory.post(
            self.edit_url,
            {"name_singular": "org", "name_plural": "orgs", "default_columns": "", "created_at": created_at},
        )
        http_request.user = self.user
        _attach_messages(http_request)
        return self.admin.edit_group_type_mapping_view(http_request, str(self.team.pk), 0)

    @parameterized.expand(
        [
            ("whole_seconds", "2026-02-20 08:15:00", int(datetime(2026, 2, 20, 8, 15, tzinfo=UTC).timestamp() * 1000)),
            (
                "with_millis",
                "2026-02-20 08:15:00.456",
                int(datetime(2026, 2, 20, 8, 15, tzinfo=UTC).timestamp() * 1000) + 456,
            ),
        ]
    )
    def test_post_sets_created_at_via_personhog(self, _name: str, created_at_raw: str, expected_millis: int) -> None:
        response = self._post(created_at_raw)

        assert response.status_code == 302
        assert response["Location"] == self.team_change_url
        update_calls = [c for c in self.fake_client.calls if c.method == "update_group_type_mapping"]
        assert len(update_calls) == 1
        update_request = update_calls[0].request
        assert "created_at" in update_request.update_mask
        assert update_request.created_at == expected_millis

    def test_post_clears_created_at_when_field_is_blank(self) -> None:
        # The mask path with no value is how the replica is told to null the column.
        response = self._post("")

        assert response.status_code == 302
        update_calls = [c for c in self.fake_client.calls if c.method == "update_group_type_mapping"]
        assert len(update_calls) == 1
        update_request = update_calls[0].request
        assert "created_at" in update_request.update_mask
        assert not update_request.HasField("created_at")
        assert (
            not self.fake_client.get_group_type_mappings_by_project_id(
                GetGroupTypeMappingsByProjectIdRequest(project_id=self.team.project_id)
            )
            .mappings[0]
            .HasField("created_at")
        )

    def test_unedited_prefill_does_not_rewrite_created_at(self) -> None:
        # Feeding GET's prefill straight back must be a no-op. Fails if the prefill loses
        # sub-second precision, or if an unchanged value is still sent in the update_mask.
        get_request = self.factory.get(self.edit_url)
        get_request.user = self.user
        _attach_messages(get_request)
        with patch("posthog.admin.admins.team_admin.render") as mock_render:
            self.admin.edit_group_type_mapping_view(get_request, str(self.team.pk), 0)
        prefilled_created_at = mock_render.call_args.args[2]["created_at_display"]

        response = self._post(prefilled_created_at)

        assert response.status_code == 302
        update_calls = [c for c in self.fake_client.calls if c.method == "update_group_type_mapping"]
        assert len(update_calls) == 1
        assert "created_at" not in update_calls[0].request.update_mask

    def test_post_invalid_created_at_redirects_without_updating(self) -> None:
        response = self._post("not-a-datetime")

        assert response.status_code == 302
        assert response["Location"] == self.edit_url
        assert not any(c.method == "update_group_type_mapping" for c in self.fake_client.calls)
