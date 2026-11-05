import re
from collections.abc import Callable
from pathlib import Path

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils.html import format_html

from parameterized import parameterized

from posthog.admin.console.organization_panels import BillingPanel, QuotaLimits
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Owner, Panel, ReasonForm
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import ConsoleRegistry, console
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Paging, Row, Table
from posthog.csp_middleware import CSPMiddleware
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.ai_gateway.backend.facade.contracts import TeamCreditAdded, TeamCreditRefused
from products.workflows.backend.facade.api import get_email_sending_state

from ee.billing.quota_limiting import QuotaResource

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
        owners = [panel.owner for record in RECORD_TYPES for panel in console.panels_for(record)] + [
            tool.owner for tool in console.tools()
        ]
        missing = sorted(
            {owner.crest for owner in owners if not (CONSOLE_ASSETS / "crests" / f"{owner.crest}.svg").is_file()}
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
                            block=Paging(number=1, num_pages=1, summary="", previous_url=None, next_url=None),
                        ),
                    )  # type: ignore[arg-type]
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
        for title in ("Overview", "Remote config cache", "Email sending", "AI gateway", "Project API token"):
            assert title in content
        assert "Needs attention" in content and "Ingested events:" in content
        for panel in console.panels_for("team"):
            assert len(panel.facts(self.team)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"

        assert f"/admin/console/organizations/{self.organization.pk}/" in content

        organization_page = self.client.get(f"/admin/console/organizations/{self.organization.pk}/")
        assert organization_page.status_code == 200
        organization_content = organization_page.content.decode()
        for title in ("Overview", "Teams", "Billing"):
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
            ("organization_action", "organization", "limit-product/?resource=events", "?resource=events#panel-billing"),
        ]
    )
    def test_an_old_django_admin_action_url_lands_on_the_console(
        self, _name: str, record: str, old: str, new: str
    ) -> None:
        obj = self.team if record == "team" else self.organization
        response = self.client.get(f"/admin/posthog/{record}/{obj.pk}/{old}")

        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/{record}s/{obj.pk}/{new}"

    def test_django_admin_team_page_points_moved_actions_to_the_console(self) -> None:
        response = self.client.get(f"/admin/posthog/team/{self.team.pk}/change/")

        assert response.status_code == 200
        content = response.content.decode()
        assert "This is the Django admin" in content
        for panel_key in ("remote-config", "email-sending", "ai-gateway", "api-token"):
            assert f"/admin/console/teams/{self.team.pk}/#panel-{panel_key}" in content

    @parameterized.expand(
        [
            ("suspend_with_reason", "suspend", {"reason": "Bounce rate above 10%"}, False, 302, True),
            ("suspend_without_reason", "suspend", {"reason": "   "}, False, 400, False),
            (
                "notification_fails_after_the_suspension",
                "suspend",
                {"reason": "Bounce rate above 10%"},
                True,
                302,
                True,
            ),
            ("operation_not_offered_in_this_state", "unsuspend", {}, False, 404, False),
        ]
    )
    @patch("posthog.admin.admins.team_admin.create_notification")
    @patch("posthog.admin.admins.team_admin.send_email_sending_suspended")
    def test_email_sending_operations_run_the_admin_view(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        notification_fails: bool,
        expected_status: int,
        expect_suspended: bool,
        send_email: MagicMock,
        _create_notification: object,
    ) -> None:
        if notification_fails:
            send_email.delay.side_effect = RuntimeError("broker down")

        response = self.client.post(f"/admin/console/teams/{self.team.pk}/email-sending/{operation_key}/", data)

        assert response.status_code == expected_status
        if expected_status == 302:
            assert response["Location"] == f"/admin/console/teams/{self.team.pk}/"
        state = get_email_sending_state(self.team.pk)
        assert (state is not None and state.suspended_at is not None) == expect_suspended

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

    @parameterized.expand([("billing_staff", True, 302), ("other_staff", False, 403)])
    @patch("posthog.admin.console.usage_reports_tool.call_command")
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_sending_usage_reports_needs_the_billing_team_group(
        self, _name: str, in_group: bool, expected_status: int, call_command: MagicMock
    ) -> None:
        if in_group:
            Group.objects.get_or_create(name="Billing Team")[0].user_set.add(self.user)

        page = self.client.get("/admin/console/tools/usage-reports/").content.decode()
        response = self.client.post("/admin/console/tools/usage-reports/send/", {"report_date": "2026-10-19"})

        assert ("Needs the Billing Team group" in page) != in_group
        assert response.status_code == expected_status
        assert call_command.called == in_group

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
