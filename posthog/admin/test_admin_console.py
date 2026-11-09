import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core.management.base import CommandError
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils.html import format_html

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.organization_panels import BillingPanel, QuotaLimits
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Gate, Operation, Owner, Panel, ReasonForm
from posthog.admin.console.registry import ConsoleRegistry, console
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Paging, Row, Table
from posthog.csp_middleware import CSPMiddleware
from posthog.llm.gateway_internal_client import AIGatewayInternalError, AIGatewayNotConfigured, LedgerEntry, Wallet
from posthog.models.data_deletion_request import DataDeletionRequest, RequestType
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.tophog.queries import TopHogFilterOptions
from posthog.models.user import User
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import create_group_type_mapping, update_group_type_mapping

from products.ai_gateway.backend.facade.contracts import TeamCreditAdded, TeamCreditRefused
from products.posthog_ai.backend.models.assistant import Conversation

from ee.billing.quota_limiting import QuotaResource
from ee.hogai.django_checkpoint.compaction import CompactionResult

TEMPLATE_DIR = Path(settings.BASE_DIR) / "posthog" / "templates" / "admin_console"
CONSOLE_ASSETS = Path(settings.BASE_DIR) / "frontend" / "public" / "admin-console"
REBUILD = "pnpm --filter=@posthog/frontend build:admin-console"

_CLASS_ATTRIBUTE = re.compile(r'class="([^"]*)"')
_TEMPLATE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")


def _selector_present(css: str, class_name: str) -> bool:
    # Tailwind and quill escape every character that is not selector-safe, so `@3xl:grid-cols-2` is
    # written `.\@3xl\:grid-cols-2`. The trailing guard stops `.flex` matching inside `.flex-1`.
    escaped = "".join(char if char.isalnum() or char in "-_" else "\\" + char for char in class_name)
    return re.search(re.escape("." + escaped) + r"(?![a-zA-Z0-9_\\-])", css) is not None


class _DuplicatePanel(Panel):
    record = "team"
    key = "overview"
    title = "Duplicate"
    owner = Owner(name="Dev experience", crest="dev-experience")


class _Tool(ConsoleTool):
    key = "some-report"
    title = "Some report"
    owner = Owner(name="Dev experience", crest="dev-experience")
    group = "Data"


def _register_twice() -> None:
    registry = ConsoleRegistry()
    registry.register_panel(type("FirstPanel", (_DuplicatePanel,), {}))
    registry.register_panel(type("SecondPanel", (_DuplicatePanel,), {}))


class TestAdminConsoleAssets(SimpleTestCase):
    def test_every_class_in_the_templates_is_in_the_compiled_stylesheet(self) -> None:
        css = (CONSOLE_ASSETS / "console.css").read_text()
        templates = sorted(TEMPLATE_DIR.glob("*.html"))
        assert templates, f"No templates found in {TEMPLATE_DIR}, so this test checks nothing."

        missing: dict[str, set[str]] = {}
        for template in templates:
            for attribute in _CLASS_ATTRIBUTE.findall(template.read_text()):
                for token in _TEMPLATE_TAG.sub(" ", attribute).split():
                    # `group/name` only marks a parent for `group-*/name:` variants and has no rule of its own.
                    if token.startswith("group/") or "{" in token or "}" in token:
                        continue
                    if not _selector_present(css, token):
                        missing.setdefault(template.name, set()).add(token)

        assert not missing, (
            "These classes are in the console templates but not in console.css, so they render unstyled. "
            f"Rebuild with `{REBUILD}`. If the class is quill's, quill may have renamed it: "
            + "; ".join(f"{name}: {sorted(classes)}" for name, classes in sorted(missing.items()))
        )

    def test_every_asset_the_templates_link_to_ships(self) -> None:
        linked = {
            name
            for template in TEMPLATE_DIR.glob("*.html")
            for name in re.findall(r"/static/admin-console/([^\"?{]+)[\"?]", template.read_text())
        }
        assert linked, "No linked assets found, so this test checks nothing."

        missing = sorted(name for name in linked if not (CONSOLE_ASSETS / name).is_file())
        assert not missing, (
            f"These assets are linked from the console templates but missing. Rebuild with `{REBUILD}`: {missing}"
        )

    def test_every_owner_crest_ships(self) -> None:
        missing = sorted(
            {
                owner.crest
                for owner in console.owners()
                if not (CONSOLE_ASSETS / "crests" / f"{owner.crest}.svg").is_file()
            }
        )

        assert not missing, (
            f"Console owners name crests the console does not ship: {missing}. Rebuild with `{REBUILD}`."
        )

    @parameterized.expand(
        [
            ("duplicate_panel_key", _register_twice, "already used"),
            (
                "panel_key_not_a_slug",
                lambda: ConsoleRegistry().register_panel(type("P", (_DuplicatePanel,), {"key": "Over view"})),
                "dash-separated key",
            ),
            (
                "blank_panel_title",
                lambda: ConsoleRegistry().register_panel(type("P", (_DuplicatePanel,), {"title": " "})),
                "needs a title",
            ),
            (
                "tool_group_outside_the_navigation",
                lambda: ConsoleRegistry().register_tool(type("T", (_Tool,), {"group": "Misc"})),
                "not one of",
            ),
            (
                "danger_operation_without_reason",
                lambda: Operation(key="wipe", label="Wipe", handler=lambda request, obj, form: None, danger=True),
                "reason",
            ),
            (
                "danger_operation_without_undo_hint",
                lambda: Operation(
                    key="wipe",
                    label="Wipe",
                    handler=lambda request, obj, form: None,
                    danger=True,
                    form_class=ReasonForm,
                ),
                "undo_hint",
            ),
            (
                "owner_gate_for_an_owner_without_a_staff_group",
                lambda: Gate.owner().resolve(Owner(name="Dev experience", crest="dev-experience")),
                "has no staff_group",
            ),
            ("fact_with_markup", lambda: Fact(label="Plan", value=format_html("<b>{}</b>", "Scale")), "plain text"),
            (
                "fact_linking_off_site",
                lambda: Fact(label="Docs", value="Read", href="//example.com/phish"),
                "starts with /",
            ),
            (
                "fact_linking_off_site_with_a_backslash",
                lambda: Fact(label="Docs", value="Read", href="/\\example.com/phish"),
                "starts with /",
            ),
            ("unknown_tool_block", lambda: Page(blocks=(Fact(label="a", value="b"),)), "not a console block"),  # type: ignore[arg-type]
            (
                "live_block_with_a_key_that_is_not_a_slug",
                lambda: Live(key="Runs list", block=Notice(text="a")),
                "lowercase and dash-separated",
            ),
            (
                "live_block_holding_paging",
                lambda: Page(
                    blocks=(
                        Live(
                            key="runs",
                            block=Paging(  # type: ignore[arg-type]
                                number=1, num_pages=1, summary="", previous_url=None, next_url=None
                            ),
                        ),
                    )
                ),
                "not a table, notice or output",
            ),
            (
                "table_row_missing_a_cell",
                lambda: Page(blocks=(Table(columns=("Team", "Months"), rows=(Row(cells=(Cell(text="a"),)),)),)),
                "1 cells for 2 columns",
            ),
        ]
    )
    def test_the_console_contract_refuses_a_contribution_that_would_render_wrong(
        self, _name: str, contribute: Callable[[], object], message: str
    ) -> None:
        with self.assertRaisesRegex(ValueError, message):
            contribute()

    @parameterized.expand(
        [
            ("fits", MAX_FACTS_PER_PANEL, MAX_FACTS_PER_PANEL, False),
            ("overflows", MAX_FACTS_PER_PANEL + 1, MAX_FACTS_PER_PANEL, True),
        ]
    )
    def test_billing_facts_count_the_limits_past_the_panel_cap(
        self, _name: str, limited_count: int, expected_facts: int, mentions_more: bool
    ) -> None:
        limited: dict[QuotaResource, int | None] = dict.fromkeys(list(QuotaResource)[:limited_count])
        with patch.object(QuotaLimits, "limited", return_value=limited):
            facts = BillingPanel().facts(Organization(name="Many limits"))

        assert len(facts) == expected_facts
        assert (facts[-1].label == "More limits") == mentions_more


class TestAdminConsoleTheme(SimpleTestCase):
    def _request(self, theme_mode: str | None) -> HttpRequest:
        request = RequestFactory().get("/admin/console/")
        request.user = User(email="staff@posthog.com", theme_mode=theme_mode)
        return request

    @parameterized.expand(
        [
            ("no_saved_preference", None, "light"),
            ("dark", "dark", "dark"),
            ("system", "system", "system"),
        ]
    )
    def test_the_console_uses_the_theme_saved_in_the_app(
        self, _name: str, theme_mode: str | None, expected: str
    ) -> None:
        html_tag = re.search(
            r"<html[^>]*>", render_to_string("admin_console/base.html", request=self._request(theme_mode))
        )

        assert html_tag is not None
        assert re.search(rf'\stheme="{expected}"', html_tag.group(0))

    @override_settings(ADMIN_PORTAL_ENABLED=True)
    def test_the_admin_csp_allows_the_inline_theme_script(self) -> None:
        response = CSPMiddleware(
            lambda request: HttpResponse(render_to_string("admin_console/base.html", request=request))
        )(self._request("system"))

        script_src = next(d for d in response["Content-Security-Policy"].split("; ") if d.startswith("script-src "))
        allowed = re.search(r"'nonce-([^']+)'", script_src)
        assert allowed is not None
        inline_scripts = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", response.content.decode())
        assert inline_scripts
        assert all(f'nonce="{allowed.group(1)}"' in tag for tag in inline_scripts), inline_scripts


class TestAdminConsoleViews(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_staff_login_is_required(self) -> None:
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/admin/console/teams/{self.team.pk}/")

        assert response.status_code == 302
        assert response["Location"].startswith("/admin/login/")

    def test_operations_need_a_csrf_token_even_with_an_api_key_parameter(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            f"/admin/console/teams/{self.team.pk}/remote-config/rebuild/?personal_api_key=phx_example", {}
        )

        assert response.status_code == 403

    def test_team_page_shows_core_and_product_panels(self) -> None:
        response = self.client.get(f"/admin/console/teams/{self.team.pk}/")

        assert response.status_code == 200
        content = response.content.decode()
        for title in (
            "Overview",
            "Remote config cache",
            "Group types",
            "Email sending",
            "AI gateway",
            "Project API token",
        ):
            assert title in content
        assert "Needs attention" in content and "Ingested events:" in content
        for panel in console.panels_for("team"):
            assert len(panel.facts(self.team)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"

        assert f"/admin/console/organizations/{self.organization.pk}/" in content
        assert f"/admin/console/tools/ai-gateway-wallet/?team={self.team.pk}" in content

        organization_page = self.client.get(f"/admin/console/organizations/{self.organization.pk}/")
        assert organization_page.status_code == 200
        organization_content = organization_page.content.decode()
        for title in ("Overview", "Teams", "Billing", "Deletion"):
            assert title in organization_content
        assert f"/admin/console/teams/{self.team.pk}/" in organization_content

        home = self.client.get("/admin/console/").content.decode()
        assert "Recently opened" in home
        assert f"/admin/console/teams/{self.team.pk}/" in home

    @parameterized.expand(
        [
            ("home", "/admin/console", "/admin/console/"),
            ("team_with_query", "/admin/console/teams/7?tab=1", "/admin/console/teams/7/?tab=1"),
        ]
    )
    def test_a_console_url_without_its_trailing_slash_redirects(self, _name: str, path: str, expected: str) -> None:
        response = self.client.get(path)

        assert response.status_code == 302
        assert response["Location"] == expected

    def test_a_name_with_one_match_opens_the_team(self) -> None:
        response = self.client.get("/admin/console/", {"q": self.team.name})

        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/teams/{self.team.pk}/"

    @parameterized.expand(
        [
            ("form_page_keeps_its_parameters", "team", "set-api-token/?from=ticket", "api-token/set/?from=ticket"),
            ("button_action_lands_on_its_panel", "team", "rebuild-cache/", "#panel-remote-config"),
            (
                "suspend_form_keeps_its_parameters",
                "team",
                "suspend-email-sending/?from=ticket",
                "email-sending/suspend/?from=ticket",
            ),
            (
                "group_type_edit_keeps_its_index_and_parameters",
                "team",
                "group-type-mapping/3/edit/?from=ticket",
                "group-types/edit-3/?from=ticket",
            ),
            ("organization_action", "organization", "limit-product/?resource=events", "?resource=events#panel-billing"),
            ("organization_deletion_form", "organization", "trigger-deletion/", "deletion/delete/"),
            (
                "deletion_request_form_page",
                "datadeletionrequest",
                "approve/?from=ticket",
                "workflow/approve/?from=ticket",
            ),
        ]
    )
    def test_an_old_django_admin_action_url_lands_on_the_console(
        self, _name: str, record: str, old: str, new: str
    ) -> None:
        obj: Model
        if record == "team":
            obj, plural = self.team, "teams"
        elif record == "organization":
            obj, plural = self.organization, "organizations"
        else:
            obj = DataDeletionRequest.objects.create(team_id=self.team.pk, request_type=RequestType.EVENT_REMOVAL)
            plural = "deletion-requests"
        response = self.client.get(f"/admin/posthog/{record}/{obj.pk}/{old}")

        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/{plural}/{obj.pk}/{new}"

    def test_django_admin_team_page_points_moved_actions_to_the_console(self) -> None:
        response = self.client.get(f"/admin/posthog/team/{self.team.pk}/change/")

        assert response.status_code == 200
        content = response.content.decode()
        assert "This is the Django admin" in content
        for panel_key in ("remote-config", "group-types", "email-sending", "ai-gateway", "api-token"):
            assert f"/admin/console/teams/{self.team.pk}/#panel-{panel_key}" in content

    @parameterized.expand(
        [
            ("new_token", "phc_console_new", 302, "phc_console_new"),
            ("blank_token", "   ", 400, "phc_console_old"),
            ("identical_token", "phc_console_old", 400, "phc_console_old"),
            ("token_of_another_team", "phc_taken", 400, "phc_console_old"),
        ]
    )
    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_set_api_token_changes_the_token_or_shows_the_form_again(
        self, _name: str, new_token: str, expected_status: int, expected_token: str, *_mocks: MagicMock
    ) -> None:
        self.team.api_token = "phc_console_old"
        self.team.save()
        Team.objects.create(organization=self.organization, api_token="phc_taken")

        response = self.client.post(
            f"/admin/console/teams/{self.team.pk}/api-token/set/", {"new_token": new_token, "reason": "Leaked key"}
        )

        assert response.status_code == expected_status
        self.team.refresh_from_db()
        assert self.team.api_token == expected_token

    @patch("products.ai_gateway.backend.facade.api.add_team_credit")
    def test_a_double_submitted_credit_form_reuses_its_idempotency_key(self, add_credit: MagicMock) -> None:
        add_credit.return_value = TeamCreditAdded(
            entry_id="entry-1", amount_usd="25", balance_usd="25", duplicate=False
        )
        form = self.client.get(f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/").content.decode()
        nonce = re.search(r'name="form_nonce" value="([^"]+)"', form)
        assert nonce is not None

        for _ in range(2):
            self.client.post(
                f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/",
                {"amount_usd": "25", "reason": "Outage goodwill", "form_nonce": nonce.group(1)},
            )

        nonces = {call.kwargs["form_nonce"] for call in add_credit.call_args_list}
        assert add_credit.call_count == 2
        assert nonces == {nonce.group(1)}

    @parameterized.expand(
        [
            (
                "balance_and_ledger",
                Wallet(
                    team_id=0,
                    known=True,
                    has_ledger=True,
                    balance="9.500000",
                    recent=[LedgerEntry("2026-06-01", "topup", "funding", "prepaid", "10.000000", "ref-1")],
                ),
                ["Balance: $9.500000", "ref-1"],
            ),
            (
                "no_gateway_account",
                Wallet(team_id=0, known=False, has_ledger=True, balance=None, recent=[]),
                ["no gateway account yet", "No ledger entries yet."],
            ),
            ("not_configured", AIGatewayNotConfigured(), ["not configured in this region"]),
            ("gateway_fails", AIGatewayInternalError("boom"), ["The wallet is unavailable: boom"]),
        ]
    )
    def test_the_old_wallet_page_opens_the_wallet_tool(
        self, _name: str, wallet: Wallet | Exception, expected: list[str]
    ) -> None:
        with patch(
            "posthog.llm.gateway_internal_client.get_wallet",
            **({"side_effect": wallet} if isinstance(wallet, Exception) else {"return_value": wallet}),
        ) as get_wallet:
            response = self.client.get(f"/admin/posthog/team/{self.team.pk}/ai-gateway-wallet/", follow=True)

        assert response.redirect_chain == [(f"/admin/console/tools/ai-gateway-wallet/?team={self.team.pk}", 302)]
        get_wallet.assert_called_once_with(self.team.pk)
        content = response.content.decode()
        for text in expected:
            assert text in content

    @patch(
        "products.ai_gateway.backend.facade.api.add_team_credit",
        side_effect=TeamCreditRefused("Failed to add credit: gateway down"),
    )
    def test_a_failed_operation_shows_the_form_again_with_what_staff_typed(self, _add_credit: MagicMock) -> None:
        response = self.client.post(
            f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/",
            {"amount_usd": "25", "reason": "Outage goodwill"},
        )

        assert response.status_code == 400
        content = response.content.decode()
        assert "gateway down" in content
        assert "Outage goodwill" in content

    @parameterized.expand(
        [
            ("limit_without_reason", "limit", {"resource": "events", "reason": " "}, True, 400, False),
            ("limit_without_billing_period", "limit", {"resource": "events", "reason": "Abuse"}, False, 400, False),
            ("limit", "limit", {"resource": "events", "reason": "Abuse"}, True, 302, True),
            ("unlimit", "unlimit", {"resource": "events"}, True, 302, False),
        ]
    )
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_billing_operations_limit_and_unlimit_a_product(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        has_billing_period: bool,
        expected_status: int,
        expect_limited: bool,
    ) -> None:
        if has_billing_period:
            self.organization.usage = {"period": ["2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"]}
            self.organization.save()
        if operation_key == "unlimit":
            self.organization.limit_product_until_end_of_billing_cycle(QuotaResource.EVENTS)

        response = self.client.post(
            f"/admin/console/organizations/{self.organization.pk}/billing/{operation_key}/", data
        )

        assert response.status_code == expected_status
        assert (QuotaResource.EVENTS in QuotaLimits.limited(self.organization)) == expect_limited

    @parameterized.expand(
        [
            ("starts_the_workflow", True, False, None, None, False, 302, True),
            ("staff_outside_the_deletion_group", False, False, None, None, False, 403, False),
            ("bulk_deletes_paused", True, True, None, None, False, 503, False),
            ("workflow_start_fails", True, False, RuntimeError("temporal down"), None, False, 500, False),
            (
                "workflow_already_running",
                True,
                False,
                WorkflowAlreadyStartedError("id", "type"),
                None,
                False,
                302,
                True,
            ),
            ("analytics_fails_before_the_start", True, False, None, RuntimeError("capture down"), False, 500, False),
            ("already_pending_when_confirmed", True, False, None, None, True, 404, True),
        ]
    )
    @patch("posthog.admin.console.organization_deletion.report_organization_deleted")
    @patch("posthog.admin.console.organization_deletion.start_delete_organization_workflow")
    def test_deleting_an_organization_needs_the_deletion_group_and_a_confirmed_preview(
        self,
        _name: str,
        in_group: bool,
        bulk_deletes_paused: bool,
        start_error: Exception | None,
        report_error: Exception | None,
        pending_before_confirm: bool,
        expected_status: int,
        expect_pending: bool,
        start: MagicMock,
        report_deleted: MagicMock,
    ) -> None:
        if in_group:
            Group.objects.get_or_create(name=DELETION_AUTHORIZED_GROUP)[0].user_set.add(self.user)
        start.side_effect = start_error
        report_deleted.side_effect = report_error
        url = f"/admin/console/organizations/{self.organization.pk}/deletion/delete/"

        with override_settings(DISABLE_BULK_DELETES=bulk_deletes_paused):
            preview = self.client.post(url, {"reason": "Customer asked to delete the organization"})
            if pending_before_confirm:
                Organization.objects.filter(pk=self.organization.pk).update(is_pending_deletion=True)
            response = (
                self.client.post(url, {"confirm_token": preview.context["confirm_token"]})
                if preview.status_code == 200
                else preview
            )

        assert response.status_code == expected_status
        if in_group:
            preview_content = preview.content.decode()
            assert self.team.name in preview_content
            # The preview links to the counts instead of running them before the confirm.
            assert f"/admin/console/tools/organization-data/?organization={self.organization.pk}" in preview_content
            assert "Early access features" not in preview_content
        assert start.called == (
            in_group and not bulk_deletes_paused and not report_error and not pending_before_confirm
        )
        if start.called:
            assert start.call_args.kwargs["team_ids"] == [self.team.pk]
            assert start.call_args.kwargs["user_id"] == self.user.pk
        self.organization.refresh_from_db()
        assert self.organization.is_pending_deletion == expect_pending

    @parameterized.expand([("active", False), ("pending_deletion", True)])
    def test_the_old_model_counts_page_opens_the_data_tool_for_every_staff_member(
        self, _name: str, pending_deletion: bool
    ) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_pending_deletion=pending_deletion)

        response = self.client.get(f"/admin/posthog/organization/{self.organization.pk}/model-counts/", follow=True)

        tool_url = f"/admin/console/tools/organization-data/?organization={self.organization.pk}"
        assert response.redirect_chain == [(tool_url, 302)]
        content = response.content.decode()
        for text in ("Early access features", "Error tracking fingerprints", "Batch exports", "persons database"):
            assert text in content
        organization_page = self.client.get(f"/admin/console/organizations/{self.organization.pk}/").content.decode()
        assert tool_url in organization_page

    @parameterized.expand(
        [
            ("compacted", True, CompactionResult(compacted=True, checkpoints_deleted=3, blobs_deleted=5), 302),
            ("nothing_to_compact", True, CompactionResult(compacted=False), 302),
            ("unknown_conversation", False, None, 404),
        ]
    )
    @patch("posthog.admin.console.conversation_checkpoints_tool.compact_conversation")
    def test_compacting_a_conversation_runs_only_for_a_conversation_that_exists(
        self,
        _name: str,
        exists: bool,
        result: CompactionResult | None,
        expected_status: int,
        compact: MagicMock,
    ) -> None:
        compact.return_value = result
        conversation_id = (
            Conversation.objects.create(team=self.team, user=self.user).id
            if exists
            else "01920000-0000-0000-0000-000000000000"
        )

        response = self.client.post(
            "/admin/console/tools/ai-conversation-checkpoints/compact/",
            {"conversation": str(conversation_id), "reason": "Thread too large to load"},
        )

        assert response.status_code == expected_status
        assert compact.called == exists
        if exists:
            compact.assert_called_once_with(str(conversation_id))

    def test_the_old_compact_url_opens_the_console_form_for_the_conversation(self) -> None:
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        response = self.client.post(f"/admin/posthog_ai/conversation/{conversation.id}/compact/", follow=True)

        tool_url = f"/admin/console/tools/ai-conversation-checkpoints/compact/?conversation={conversation.id}"
        assert response.redirect_chain == [(tool_url, 302)]
        assert str(conversation.id) in response.content.decode()

    @parameterized.expand([("billing_staff", True, 302), ("other_staff", False, 403)])
    @patch("posthog.admin.console.usage_reports_tool.call_command")
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_sending_usage_reports_needs_the_billing_team_group(
        self, _name: str, in_group: bool, expected_status: int, call_command: MagicMock
    ) -> None:
        if in_group:
            Group.objects.get_or_create(name="Billing Team")[0].user_set.add(self.user)

        page = self.client.get("/admin/console/tools/usage-reports/").content.decode()
        form = self.client.get("/admin/console/tools/usage-reports/send/")
        response = self.client.post("/admin/console/tools/usage-reports/send/", {"report_date": "2026-10-19"})

        assert ("Only members of the Billing Team group can run this" in page) != in_group
        assert form.status_code == (200 if in_group else 403)
        assert response.status_code == expected_status
        assert call_command.called == in_group

    @parameterized.expand(
        [
            ("queued", "2026-07-15", None, 302, True),
            (
                "refused_by_the_command",
                "2026-07-15",
                CommandError("A run for 2026-07-15 was already dispatched."),
                400,
                True,
            ),
            ("date_too_far_ahead", "2026-07-30", None, 400, False),
        ]
    )
    @patch("products.ai_observability.backend.admin.call_command")
    @time_machine.travel("2026-07-22T12:00:00Z", tick=False)
    def test_sending_the_ai_observability_usage_report_queues_it_or_shows_why_not(
        self,
        _name: str,
        report_date: str,
        command_error: Exception | None,
        expected_status: int,
        expect_called: bool,
        call_command: MagicMock,
    ) -> None:
        call_command.side_effect = command_error

        response = self.client.post(
            "/admin/console/tools/ai-observability/send-usage-report/", {"report_date": report_date}
        )

        assert response.status_code == expected_status
        assert call_command.called == expect_called
        if expect_called:
            call_command.assert_called_once_with(
                "send_ai_observability_usage_report", f"--date={report_date}", "--async"
            )
        if command_error is not None:
            assert "already dispatched" in response.content.decode()

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_events_retention_tool_lists_the_teams_of_an_organization_with_a_default(self) -> None:
        empty = self.client.get("/admin/console/tools/events-retention/")
        assert empty.status_code == 200
        assert "No team has a deletion retention yet" in empty.content.decode()

        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=13
        )
        response = self.client.get("/admin/events-retention/", follow=True)

        assert response.redirect_chain == [("/admin/console/tools/events-retention/", 302)]
        content = response.content.decode()
        assert "Events retention moved to PostHog Admin" in content
        assert f"/admin/console/teams/{self.team.pk}/" in content
        assert "Organization default" in content
        assert "September 2025" in content

    @patch("posthog.admin.console.tophog_tool.query_tophog_filter_options")
    @patch("posthog.admin.console.tophog_tool.query_tophog_metrics")
    def test_tophog_links_each_entry_to_the_restrictions_of_its_token(
        self, query_metrics: MagicMock, query_filter_options: MagicMock
    ) -> None:
        query_filter_options.return_value = TopHogFilterOptions(pipelines=["analytics"], lanes=["main"])
        query_metrics.return_value = [
            {
                "metric": "emitted_events",
                "type": "sum",
                "key": {"team_id": str(self.team.pk), "distinct_id": "did"},
                "total": 1200,
                "obs": 3,
                "pipelines": ["analytics"],
                "lanes": ["main"],
            }
        ]

        response = self.client.get("/admin/tophog/?preset=1h&pipeline=analytics", follow=True)

        assert response.redirect_chain == [("/admin/console/tools/tophog/?preset=1h&pipeline=analytics", 302)]
        assert query_metrics.call_args.kwargs == {"pipeline": "analytics", "lane": None}
        content = response.content.decode()
        assert "TopHog moved to PostHog Admin" in content
        assert "emitted_events (sum)" in content
        entry_url = (
            f"/admin/console/tools/tophog/?token={self.team.api_token}"
            f"&amp;team_id={self.team.pk}&amp;distinct_id=did&amp;pipelines=analytics"
        )
        assert entry_url in content
        # The range notice refreshes with the entries, so its pin link follows the window on screen.
        assert 'data-console-live="/admin/console/tools/tophog/live/range/' in content
        live_range = self.client.get("/admin/console/tools/tophog/live/range/?preset=1h")
        assert "Pin this time range" in live_range.content.decode()

    @parameterized.expand(
        [
            ("with_reason", {"reason": "Event flood"}, 302, ["existing", "new-id"]),
            ("without_reason", {"reason": "  "}, 400, ["existing"]),
        ]
    )
    def test_tophog_extends_a_restriction_to_cover_an_entry(
        self, _name: str, data: dict[str, str], expected_status: int, expected_distinct_ids: list[str]
    ) -> None:
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_tophog", restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION, distinct_ids=["existing"]
        )
        page = self.client.get(
            "/admin/tophog/restrictions/?token=phc_tophog&distinct_id=new-id&pipelines=sessionreplay", follow=True
        )
        assert page.redirect_chain == [
            ("/admin/console/tools/tophog/?token=phc_tophog&distinct_id=new-id&pipelines=sessionreplay", 302)
        ]
        content = page.content.decode()
        assert "Extend the drop event from ingestion restriction" in content
        assert (
            "/admin/posthog/eventingestionrestrictionconfig/add/"
            "?token=phc_tophog&amp;distinct_ids=new-id&amp;pipelines=session_recordings"
        ) in content

        response = self.client.post(
            f"/admin/console/tools/tophog/extend-{restriction.pk}/?token=phc_tophog&distinct_id=new-id", data
        )

        assert response.status_code == expected_status
        restriction.refresh_from_db()
        assert restriction.distinct_ids == expected_distinct_ids

    @patch("posthog.models.distinct_id_usage.report.DistinctIdUsageQueries")
    def test_distinct_id_usage_report_keeps_the_old_query_and_marks_restrictions(self, queries: MagicMock) -> None:
        EventIngestionRestrictionConfig.objects.create(
            token=self.team.api_token,
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["heavy-user"],
        )
        EventIngestionRestrictionConfig.objects.create(
            token=self.team.api_token,
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            distinct_ids=["other-user"],
        )
        redirected_team = Team.objects.create(organization=self.organization, name="Redirected")
        EventIngestionRestrictionConfig.objects.create(
            token=redirected_team.api_token,
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            distinct_ids=["other-user"],
        )
        queries.high_usage.return_value = [(self.team.pk, "heavy-user", 200_000, 300_000, 66.67)]
        queries.high_cardinality.side_effect = RuntimeError("Timeout exceeded")
        queries.distinct_id_bursts.return_value = [
            (self.team.pk, "bursty-user", datetime(2026, 11, 6, 10, 5, tzinfo=UTC), 150_000),
            (redirected_team.pk, "bursty-user", datetime(2026, 11, 6, 10, 5, tzinfo=UTC), 150_000),
        ]
        queries.team_bursts.return_value = []
        query = (
            "datetime_from=2026-11-06T04%3A00&datetime_to=2026-11-06T10%3A00&high_usage_percentage_threshold=30"
            "&high_usage_min_events_threshold=10000&high_usage_distinct_id_min_events=100000"
            "&high_cardinality_threshold=1000000&burst_distinct_id_threshold=100000&burst_team_threshold=500000"
        )

        response = self.client.get(f"/admin/distinct-id-usage/?{query}", follow=True)

        assert response.redirect_chain == [(f"/admin/console/tools/distinct-id-usage/?{query}", 302)]
        content = response.content.decode()
        assert "Applied: Skip person processing" in content
        assert "Not in list: Skip person processing" in content
        assert "Not in list: Redirect to dlq" in content
        # The restrict form offers no redirect types, so a redirect must never be prefilled.
        assert "restriction_type=skip_person_processing" in content
        assert "restriction_type=redirect_to_dlq" not in content
        assert "The high cardinality query failed: Timeout exceeded" in content
        assert "/admin/console/tools/distinct-id-usage/restrict/?" in content

    @parameterized.expand(
        [
            ("creates_a_restriction", None, "Spam traffic", 302, ["heavy-user"]),
            ("adds_to_the_existing_restriction", ["other-user"], "Spam traffic", 302, ["other-user", "heavy-user"]),
            ("refuses_to_narrow_a_restriction_on_every_distinct_id", [], "Spam traffic", 400, []),
            ("needs_a_reason", None, "  ", 400, None),
            (
                "refuses_a_restriction_of_other_pipelines",
                ["other-user"],
                "Spam traffic",
                400,
                ["other-user"],
                ("session_recordings",),
            ),
        ]
    )
    def test_restrict_a_distinct_id(
        self,
        _name: str,
        existing_distinct_ids: list[str] | None,
        reason: str,
        expected_status: int,
        expected_distinct_ids: list[str] | None,
        pipelines: tuple[str, ...] = ("analytics",),
    ) -> None:
        if existing_distinct_ids is not None:
            EventIngestionRestrictionConfig.objects.create(
                token=self.team.api_token,
                restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
                distinct_ids=existing_distinct_ids,
                pipelines=list(pipelines),
            )

        response = self.client.post(
            "/admin/console/tools/distinct-id-usage/restrict/",
            {
                "token": self.team.api_token,
                "distinct_id": "heavy-user",
                "restriction_type": RestrictionType.DROP_EVENT_FROM_INGESTION,
                "reason": reason,
            },
        )

        assert response.status_code == expected_status
        restriction = EventIngestionRestrictionConfig.objects.filter(token=self.team.api_token).first()
        assert (restriction.distinct_ids if restriction else None) == expected_distinct_ids

    @parameterized.expand(
        [
            ("cached_config", ({"token": "phc_cached_config"}, "redis"), "phc_cached_config"),
            ("team_cached_as_missing", (None, "redis"), "says that this team does not exist"),
            ("nothing_cached", (None, None), "Nothing is cached for this team"),
        ]
    )
    @patch("posthog.admin.console.remote_config_tool.RemoteConfig.get_hypercache")
    def test_the_old_view_cache_url_shows_the_cached_config_in_the_console(
        self, _name: str, cached: tuple[object, str | None], expected: str, get_hypercache: MagicMock
    ) -> None:
        get_hypercache.return_value.get_cache_key.return_value = "cache/team_tokens/config.json"
        get_hypercache.return_value.peek_from_cache_with_source.return_value = cached

        response = self.client.get(f"/admin/posthog/team/{self.team.pk}/view-cache/", follow=True)

        assert response.redirect_chain == [(f"/admin/console/tools/remote-config-cache/?team={self.team.pk}", 302)]
        content = response.content.decode()
        assert "The cached config view moved to PostHog Admin" in content
        assert "cache/team_tokens/config.json" in content
        assert expected in content

    @parameterized.expand([("missing", ""), ("not_a_number", "abc"), ("unicode_digit", "²")])
    def test_the_remote_config_cache_tool_asks_for_a_team_when_the_team_is_not_a_team_id(
        self, _name: str, team: str
    ) -> None:
        response = self.client.get("/admin/console/tools/remote-config-cache/", {"team": team})

        assert response.status_code == 200
        assert "Open this page from the Remote config cache panel" in response.content.decode()

    @parameterized.expand(
        [
            (
                "rename_keeps_the_created_time",
                {"name_singular": "Company"},
                ["name_singular"],
                None,
                "Singular name: Not set to Company",
            ),
            (
                "created_time_to_the_millisecond",
                {"created_at": "2026-02-20 08:15:00.456"},
                ["created_at"],
                int(datetime(2026, 2, 20, 8, 15, tzinfo=UTC).timestamp() * 1000) + 456,
                "Created (UTC): 2026-01-15 10:30:00.123 to 2026-02-20 08:15:00.456",
            ),
            (
                "cleared_created_time",
                {"created_at": ""},
                ["created_at"],
                None,
                "Created (UTC): 2026-01-15 10:30:00.123 to Not set",
            ),
            (
                "cleared_default_columns",
                {"default_columns": ""},
                ["default_columns"],
                None,
                'Default columns: ["name"] to Not set',
            ),
            ("unchanged_form", {}, None, None, ""),
            ("invalid_created_time", {"created_at": "not-a-datetime"}, None, None, ""),
            ("impossible_created_time", {"created_at": "2026-02-30 10:30:00"}, None, None, ""),
        ]
    )
    def test_editing_a_group_type_previews_then_writes_only_the_changed_fields(
        self,
        _name: str,
        changes: dict[str, str],
        expected_mask: list[str] | None,
        expected_created_at: int | None,
        expected_message: str,
    ) -> None:
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            default_columns=["name"],
            created_at=datetime(2026, 1, 15, 10, 30, 0, 123000, tzinfo=UTC),
        )
        url = f"/admin/console/teams/{self.team.pk}/group-types/edit-0/"
        prefilled = self.client.get(url).context["form"].initial

        preview = self.client.post(url, {**prefilled, **changes, "reason": "Customer asked"})
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert updates == []
        if expected_mask is None:
            assert preview.status_code == 400
            return
        assert preview.status_code == 200
        assert "After saving" in preview.content.decode()

        saved = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert saved.status_code == 302
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert len(updates) == 1
        assert list(updates[0].update_mask) == expected_mask
        if "created_at" in expected_mask:
            assert (updates[0].created_at if updates[0].HasField("created_at") else None) == expected_created_at
        assert expected_message in " ".join(str(message) for message in get_messages(saved.wsgi_request))

    @parameterized.expand([("before_the_preview", True), ("before_the_confirm", False)])
    def test_editing_a_group_type_refuses_when_the_group_type_changed_since_the_form_opened(
        self, _name: str, change_before_preview: bool
    ) -> None:
        mapping = create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            default_columns=["name"],
        )
        url = f"/admin/console/teams/{self.team.pk}/group-types/edit-0/"
        prefilled = self.client.get(url).context["form"].initial
        mapping.default_columns = ["name", "email"]

        if change_before_preview:
            update_group_type_mapping(mapping)
        preview = self.client.post(url, {**prefilled, "name_singular": "Company", "reason": "Customer asked"})
        if change_before_preview:
            assert preview.status_code == 400
            assert "changed since you opened this form" in preview.content.decode()
            return
        update_group_type_mapping(mapping)
        saved = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert saved.status_code == 409
        assert "changed since you opened this form" in saved.content.decode()
        updates = [call.request for call in get_active_fake().calls if call.method == "update_group_type_mapping"]
        assert updates == []
