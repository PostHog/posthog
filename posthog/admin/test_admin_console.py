import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import ANY, MagicMock, patch

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.db.models import PROTECT, Model
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone
from django.utils.html import format_html

from django_otp.plugins.otp_totp.models import TOTPDevice
from loginas import settings as la_settings
from parameterized import parameterized
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.organization_panels import BillingPanel, QuotaLimits
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Gate, Operation, Owner, Panel, ReasonForm
from posthog.admin.console.registry import ConsoleRegistry, console
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Paging, Row, Table
from posthog.admin.console.user_panels import is_acting_as
from posthog.csp_middleware import CSPMiddleware
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.data_deletion_request import DataDeletionRequest, RequestType
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.project_secret_api_key import RevokedTeamSecretToken
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.personhog_client.fake_client import get_active_fake
from posthog.session.models import Session
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.test.api_keys import create_project_secret_api_key
from posthog.test.persons import create_group_type_mapping, update_group_type_mapping

from products.ai_gateway.backend.facade.contracts import TeamCreditAdded, TeamCreditRefused
from products.workflows.backend.facade.api import get_email_sending_state

from ee.billing.quota_limiting import QuotaResource

TEMPLATE_DIR = Path(settings.BASE_DIR) / "posthog" / "templates" / "admin_console"
PROJECT_PANEL_TITLES = ("Overview", "Deletion")
USER_PANEL_TITLES = ("Overview", "Organizations", "Sign-in", "Personal API keys", "Deletion")
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
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

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
            "Project secret API keys",
        ):
            assert title in content
        assert "Needs attention" in content and "Ingested events:" in content
        for panel in console.panels_for("team"):
            assert len(panel.facts(self.team)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"

        assert f"/admin/console/organizations/{self.organization.pk}/" in content
        assert f"/admin/console/projects/{self.project.pk}/" in content
        assert f"/admin/console/users/{self.user.pk}/" in content

        organization_page = self.client.get(f"/admin/console/organizations/{self.organization.pk}/")
        assert organization_page.status_code == 200
        organization_content = organization_page.content.decode()
        for title in ("Overview", "Teams", "Billing"):
            assert title in organization_content
        assert f"/admin/console/teams/{self.team.pk}/" in organization_content

        for record, path, titles in (
            ("project", f"/admin/console/projects/{self.project.pk}/", PROJECT_PANEL_TITLES),
            ("user", f"/admin/console/users/{self.user.pk}/", USER_PANEL_TITLES),
        ):
            record_page = self.client.get(path)
            assert record_page.status_code == 200
            record_content = record_page.content.decode()
            for title in titles:
                assert title in record_content, f"{title} is missing from the {record} page"
            assert f"/admin/console/organizations/{self.organization.pk}/" in record_content
            obj = self.project if record == "project" else self.user
            for panel in console.panels_for(record):
                assert len(panel.facts(obj)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"
        assert (
            f"/admin/console/teams/{self.team.pk}/"
            in self.client.get(f"/admin/console/projects/{self.project.pk}/").content.decode()
        )

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

    @parameterized.expand([("team_name", "team"), ("user_email_in_another_case", "user")])
    def test_a_lookup_with_one_match_opens_its_page(self, _name: str, record: str) -> None:
        if record == "team":
            query, expected = self.team.name, f"/admin/console/teams/{self.team.pk}/"
        else:
            query, expected = self.user.email.upper(), f"/admin/console/users/{self.user.pk}/"

        response = self.client.get("/admin/console/", {"q": query})

        assert response.status_code == 302
        assert response["Location"] == expected

    @parameterized.expand(
        [
            ("form_page_keeps_its_parameters", "team", "set-api-token/?from=ticket", "api-token/set/?from=ticket"),
            ("button_action_lands_on_its_panel", "team", "rebuild-cache/", "#panel-remote-config"),
            (
                "group_type_edit_keeps_its_index_and_parameters",
                "team",
                "group-type-mapping/3/edit/?from=ticket",
                "group-types/edit-3/?from=ticket",
            ),
            ("organization_action", "organization", "limit-product/?resource=events", "?resource=events#panel-billing"),
            (
                "deletion_request_form_page",
                "datadeletionrequest",
                "approve/?from=ticket",
                "workflow/approve/?from=ticket",
            ),
            ("project_deletion", "project", "trigger-deletion/?from=ticket", "?from=ticket#panel-deletion"),
            ("project_delete_now", "project", "delete-now/", "#panel-deletion"),
            ("user_deletion", "user", "delete/?from=ticket", "deletion/delete/?from=ticket"),
            ("user_password_lands_on_sign_in", "user", "password/", "#panel-sign-in"),
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
        elif record == "project":
            obj, plural = self.project, "projects"
        elif record == "user":
            obj, plural = self.user, "users"
        else:
            obj = DataDeletionRequest.objects.create(team_id=self.team.pk, request_type=RequestType.EVENT_REMOVAL)
            plural = "deletion-requests"
        response = self.client.get(f"/admin/posthog/{record}/{obj.pk}/{old}")

        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/{plural}/{obj.pk}/{new}"

    @parameterized.expand(
        [
            ("team", ("remote-config", "group-types", "email-sending", "ai-gateway", "api-token")),
            ("project", ("deletion",)),
            ("user", ("sign-in", "deletion")),
        ]
    )
    def test_django_admin_page_points_moved_actions_to_the_console(
        self, record: str, panel_keys: tuple[str, ...]
    ) -> None:
        obj: Model = {"team": self.team, "project": self.project, "user": self.user}[record]
        plural = f"{record}s"

        response = self.client.get(f"/admin/posthog/{record}/{obj.pk}/change/")

        assert response.status_code == 200
        content = response.content.decode()
        assert "This is the Django admin" in content
        for panel_key in panel_keys:
            assert f"/admin/console/{plural}/{obj.pk}/#panel-{panel_key}" in content

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
        form = self.client.get("/admin/console/tools/usage-reports/send/")
        response = self.client.post("/admin/console/tools/usage-reports/send/", {"report_date": "2026-10-19"})

        assert ("Only members of the Billing Team group can run this" in page) != in_group
        assert form.status_code == (200 if in_group else 403)
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


@time_machine.travel("2026-10-20T12:00:00Z", tick=False)
class TestAdminConsoleProjectDeletion(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.user.groups.add(Group.objects.get_or_create(name=DELETION_AUTHORIZED_GROUP)[0])
        self.client.force_login(self.user)
        start_patcher = patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
        self.start = start_patcher.start()
        self.addCleanup(start_patcher.stop)

    def _mark_pending(self, hours: float) -> datetime:
        scheduled_at = timezone.now() + timedelta(hours=hours)
        Project.objects.filter(pk=self.project.pk).update(is_pending_deletion=True, deletion_scheduled_at=scheduled_at)
        return scheduled_at

    def _post(self, operation_key: str, start_side_effect: Exception | None = None):
        self.start.side_effect = start_side_effect
        return self.client.post(
            f"/admin/console/projects/{self.project.pk}/deletion/{operation_key}/", {"reason": "Customer asked"}
        )

    @parameterized.expand([("with_ingested_data", True, timedelta(hours=48)), ("without_ingested_data", False, None)])
    def test_deleting_a_project_starts_the_workflow_and_marks_it_pending(
        self, _name: str, has_ingested_data: bool, expected_delay: timedelta | None
    ) -> None:
        self.team.ingested_event = has_ingested_data
        self.team.save(update_fields=["ingested_event"])

        response = self._post("delete")

        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/projects/{self.project.pk}/"
        self.start.assert_called_once()
        kwargs = self.start.call_args.kwargs
        assert (kwargs["project_id"], kwargs["team_ids"], kwargs["user_id"], kwargs["project_name"]) == (
            self.project.pk,
            [self.team.pk],
            self.user.pk,
            self.project.name,
        )
        assert kwargs["start_delay"] == expected_delay
        self.project.refresh_from_db()
        assert self.project.is_pending_deletion
        assert self.project.deletion_scheduled_at == timezone.now() + (expected_delay or timedelta())

    @parameterized.expand(
        [
            ("form_page_only", "get", None, 200, False, False),
            ("staff_outside_the_deletion_group", "other_staff", None, 403, False, False),
            ("bulk_deletes_disabled", "bulk_deletes_disabled", None, 503, False, False),
            ("already_pending", "already_pending", None, 404, False, True),
            ("workflow_already_running", None, WorkflowAlreadyStartedError("id", "type"), 302, True, True),
            ("workflow_fails_to_start", None, RuntimeError("temporal unavailable"), 500, True, False),
        ]
    )
    def test_deleting_a_project_refuses_or_rolls_back(
        self,
        _name: str,
        state: str | None,
        start_side_effect: Exception | None,
        expected_status: int,
        expect_started: bool,
        expect_pending: bool,
    ) -> None:
        if state == "other_staff":
            self.user.groups.clear()
        elif state == "already_pending":
            self._mark_pending(hours=48)

        with override_settings(DISABLE_BULK_DELETES=state == "bulk_deletes_disabled"):
            if state == "get":
                response = self.client.get(f"/admin/console/projects/{self.project.pk}/deletion/delete/")
            else:
                response = self._post("delete", start_side_effect)

        assert response.status_code == expected_status
        assert self.start.called == expect_started
        self.project.refresh_from_db()
        assert self.project.is_pending_deletion == expect_pending

    def test_delete_now_cancels_the_wait_and_starts_the_workflow(self) -> None:
        self._mark_pending(hours=48)

        response = self._post("delete-now")

        assert response.status_code == 302
        self.start.assert_called_once()
        assert self.start.call_args.kwargs["start_delay"] is None
        assert self.start.call_args.kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.TERMINATE_EXISTING
        self.project.refresh_from_db()
        assert self.project.deletion_scheduled_at == timezone.now()

    @parameterized.expand(
        [
            ("deletion_already_started", -1, None, None, 404),
            ("staff_outside_the_deletion_group", 48, "other_staff", None, 403),
            ("bulk_deletes_disabled", 48, "bulk_deletes_disabled", None, 503),
            ("workflow_fails_to_start", 48, None, RuntimeError("temporal unavailable"), 500),
        ]
    )
    def test_delete_now_keeps_the_schedule_when_it_cannot_start(
        self,
        _name: str,
        hours_until_deletion: int,
        state: str | None,
        start_side_effect: Exception | None,
        expected_status: int,
    ) -> None:
        scheduled_at = self._mark_pending(hours=hours_until_deletion)
        if state == "other_staff":
            self.user.groups.clear()

        with override_settings(DISABLE_BULK_DELETES=state == "bulk_deletes_disabled"):
            response = self._post("delete-now", start_side_effect)

        assert response.status_code == expected_status
        assert self.start.called == (start_side_effect is not None)
        self.project.refresh_from_db()
        assert self.project.is_pending_deletion
        assert self.project.deletion_scheduled_at == scheduled_at


class TestAdminConsoleUserSignIn(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.target = User.objects.create_and_join(self.organization, "signin-target@example.com", None)

    def _url(self, operation_key: str) -> str:
        return f"/admin/console/users/{self.target.pk}/sign-in/{operation_key}/"

    @parameterized.expand(
        [
            ("verification", "send-verification", {}, False, 302),
            ("verification_for_a_verified_user", "send-verification", {}, True, 404),
            ("password_reset", "send-password-reset", {}, False, 302),
            ("two_factor_reset", "send-2fa-reset", {"reason": "Lost their phone, ticket 42"}, True, 302),
            ("two_factor_reset_without_a_reason", "send-2fa-reset", {"reason": " "}, True, 400),
            ("two_factor_reset_without_two_factor", "send-2fa-reset", {"reason": "Lost their phone"}, False, 404),
        ]
    )
    @patch("posthog.admin.console.user_panels.send_two_factor_reset_email")
    @patch("posthog.admin.console.user_panels.send_password_reset")
    @patch("posthog.admin.console.user_panels.email_verification_code_verifier")
    def test_sign_in_emails_go_out_only_when_they_apply(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        target_state: bool,
        expected_status: int,
        verifier: MagicMock,
        send_password_reset: MagicMock,
        send_two_factor_reset_email: MagicMock,
    ) -> None:
        if operation_key == "send-verification":
            self.target.is_email_verified = target_state
            self.target.save()
        elif target_state:
            TOTPDevice.objects.create(user=self.target, name="default", confirmed=True)

        response = self.client.post(self._url(operation_key), data)

        assert response.status_code == expected_status
        sent = {
            "send-verification": verifier.send_code,
            "send-password-reset": send_password_reset.delay,
            "send-2fa-reset": send_two_factor_reset_email.delay,
        }[operation_key]
        assert sent.called == (expected_status == 302)
        if operation_key == "send-password-reset":
            self.target.refresh_from_db()
            assert self.target.requested_password_reset_at is not None
            user_pk, token = sent.call_args.args[:2]
            assert user_pk == self.target.pk
            assert isinstance(token, str) and token

    def test_revoking_sessions_signs_out_only_that_user(self) -> None:
        engine = import_module(settings.SESSION_ENGINE)

        def login_session(user: User) -> str:
            store = engine.SessionStore()
            store[SESSION_KEY] = str(user.pk)
            store.create()
            return store.session_key

        target_keys = [login_session(self.target), login_session(self.target)]
        other_key = login_session(User.objects.create_and_join(self.organization, "other@example.com", None))

        response = self.client.post(self._url("revoke-sessions"), {"reason": "Account compromised"})

        assert response.status_code == 302
        assert not Session.objects.filter(session_key__in=target_keys).exists()
        assert Session.objects.filter(session_key=other_key).exists()


class _RefusesDeletionAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False


class TestAdminConsoleUserDeletion(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.target = User.objects.create_and_join(self.organization, "delete-me@example.com", None)
        self.url = f"/admin/console/users/{self.target.pk}/deletion/delete/"

    def _preview(self, reason: str = "Duplicate account after an email change"):
        return self.client.post(self.url, {"reason": reason})

    def _counts(self, preview) -> dict[str, str]:
        table = next(block for block in preview.context["page"].blocks if isinstance(block, Table))
        return {row.cells[0].text: row.cells[1].text for row in table.rows if isinstance(row, Row)}

    def _deletion_logs(self, target_id: int):
        return ActivityLog.objects.filter(scope="User", activity="deleted", item_id=str(target_id))

    @parameterized.expand([("under_the_cap", 100, "2"), ("over_the_cap", 1, "1+")])
    def test_the_preview_counts_the_cascade_instead_of_listing_every_row(
        self, _name: str, cap: int, expected_views: str
    ) -> None:
        for session_id in ("one", "two"):
            SessionRecordingViewed.objects.create(team=self.team, user=self.target, session_id=session_id)

        with patch("posthog.admin.console.user_panels.DELETION_SUMMARY_COUNT_CAP", cap):
            preview = self._preview()

        assert preview.status_code == 200
        counts = self._counts(preview)
        assert counts[str(User._meta.verbose_name_plural)] == "1"
        assert counts[str(SessionRecordingViewed._meta.verbose_name_plural)] == expected_views
        assert counts[str(OrganizationMembership._meta.verbose_name_plural)] == "1"
        assert User.objects.filter(pk=self.target.pk).exists()

    def test_a_delete_without_a_reason_keeps_the_user(self) -> None:
        response = self._preview(reason="  ")

        assert response.status_code == 400
        assert User.objects.filter(pk=self.target.pk).exists()

    def test_the_confirmed_delete_records_the_reason_for_every_organization(self) -> None:
        other_organization, _, _ = User.objects.bootstrap("Other org", "owner@example.com", None)
        self.target.join(organization=other_organization)
        target_id = self.target.pk

        preview = self._preview()
        response = self.client.post(self.url, {"confirm_token": preview.context["confirm_token"]})

        assert response.status_code == 302
        assert response["Location"] == "/admin/console/"
        assert not User.objects.filter(pk=target_id).exists()
        logs = self._deletion_logs(target_id)
        assert {log.organization_id for log in logs} == {self.organization.id, other_organization.id}
        for log in logs:
            assert log.user == self.user
            assert (log.detail or {}).get("context") == {
                "reason": "Duplicate account after an email change",
                "email": "delete-me@example.com",
            }

    def test_the_reason_reaches_the_admin_log_when_the_user_has_no_organization(self) -> None:
        # An ActivityLog row needs an organization or team to be scoped to, so the admin log is the only record.
        self.target.organization_memberships.all().delete()
        target_id = self.target.pk

        preview = self._preview(reason="Requested by the customer")
        self.client.post(self.url, {"confirm_token": preview.context["confirm_token"]})

        assert not User.objects.filter(pk=target_id).exists()
        assert not self._deletion_logs(target_id).exists()
        entry = LogEntry.objects.get(object_id=str(target_id), action_flag=DELETION)
        assert "Requested by the customer" in entry.change_message

    def test_a_protected_relation_refuses_the_delete_before_it_starts(self) -> None:
        # Django raises ProtectedError from inside the delete, with part of the cascade already gone.
        membership_user_field = OrganizationMembership._meta.get_field("user")

        with patch.object(membership_user_field.remote_field, "on_delete", PROTECT):
            response = self._preview()

        assert response.status_code == 400
        assert User.objects.filter(pk=self.target.pk).exists()

    @parameterized.expand([("with_recorded_views", 1, 400), ("without_recorded_views", 0, 200)])
    def test_an_admin_that_refuses_deletion_blocks_the_cascade_through_its_model(
        self, _name: str, view_count: int, expected_status: int
    ) -> None:
        for index in range(view_count):
            SessionRecordingViewed.objects.create(team=self.team, user=self.target, session_id=str(index))

        with patch.dict(
            admin.site._registry, {SessionRecordingViewed: _RefusesDeletionAdmin(SessionRecordingViewed, admin.site)}
        ):
            response = self._preview()

        assert response.status_code == expected_status
        assert User.objects.filter(pk=self.target.pk).exists()

    @parameterized.expand([("own_account", "self"), ("impersonated_account", "impersonated")])
    def test_the_confirm_refuses_an_account_the_staff_member_acts_as(self, _name: str, account: str) -> None:
        target = self.user if account == "self" else self.target
        url = f"/admin/console/users/{target.pk}/deletion/delete/"
        with patch("posthog.admin.console.user_panels.is_acting_as", return_value=False):
            preview = self.client.post(url, {"reason": "Duplicate account"})
        assert preview.status_code == 200

        impersonated = self.target if account == "impersonated" else None
        with patch("posthog.admin.console.user_panels.get_impersonated_user", return_value=impersonated):
            response = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert response.status_code == 409
        assert User.objects.filter(pk=target.pk).exists()

    @parameterized.expand([("self", True), ("impersonated_user", True), ("someone_else", False)])
    def test_staff_cannot_delete_the_account_they_act_as(self, account: str, expected: bool) -> None:
        request = RequestFactory().post(self.url)
        request.user = self.user
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if account == "impersonated_user":
            # AdminImpersonationMiddleware swaps `request.user` back to the staff operator on /admin/ paths.
            request.session[la_settings.USER_SESSION_FLAG] = "signed-original-user"
            request.session[SESSION_KEY] = str(self.target.pk)
            request.session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"

        assert is_acting_as(request, self.user if account == "self" else self.target) == expected

    def test_django_admin_offers_no_delete_of_its_own(self) -> None:
        user_admin = admin.site._registry[User]
        request = RequestFactory().get("/admin/posthog/user/")
        request.user = self.user

        assert not user_admin.has_delete_permission(request, self.target)
        assert "delete_selected" not in user_admin.get_actions(request)


class TestAdminConsoleApiKeys(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _personal_key(self) -> PersonalAPIKey:
        token = generate_random_token_personal()
        return PersonalAPIKey.objects.create(
            user=self.user,
            label="Leaked key",
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
            scopes=["*"],
        )

    @patch("posthog.admin.console.api_key_panels.send_personal_api_key_exposed")
    def test_rolling_a_personal_api_key_notifies_the_user(self, exposed: MagicMock) -> None:
        key = self._personal_key()
        old_secure_value, old_mask_value = key.secure_value, key.mask_value

        response = self.client.post(
            f"/admin/console/users/{self.user.pk}/personal-api-keys/roll/",
            {"key": key.pk, "exposed_at": "https://example.com/leak", "reason": "Found in a public repo"},
        )

        assert response.status_code == 302
        key.refresh_from_db()
        assert key.secure_value != old_secure_value
        assert key.last_rolled_at is not None
        exposed.assert_called_once_with(
            self.user.id, key.id, old_mask_value, "This key was detected at https://example.com/leak."
        )

    @patch("posthog.api.project_secret_api_key.send_feature_flags_secure_api_key_exposed")
    @patch("posthog.api.project_secret_api_key.send_project_secret_api_key_exposed")
    def test_revoking_a_secret_api_key_rolls_it_or_deletes_a_legacy_mirror(
        self, psak_exposed: MagicMock, legacy_exposed: MagicMock
    ) -> None:
        key, _ = create_project_secret_api_key(team=self.team, created_by=self.user, label="Admin key")
        old_secure_value = key.secure_value
        legacy_token = "phs_legacy_token_mirrored_in_console"
        self.team.secret_api_token = legacy_token
        self.team.save()
        mirrored, _ = create_project_secret_api_key(team=self.team, label="Migrated legacy key", value=legacy_token)
        url = f"/admin/console/teams/{self.team.pk}/secret-api-keys/revoke/"

        rolled = self.client.post(url, {"key": key.pk, "exposed_at": "", "reason": "Found in a public repo"})
        deleted = self.client.post(url, {"key": mirrored.pk, "exposed_at": "", "reason": "Found in a public repo"})

        assert (rolled.status_code, deleted.status_code) == (302, 302)
        key.refresh_from_db()
        assert key.secure_value != old_secure_value
        psak_exposed.assert_called_once_with(self.team.id, key.id, ANY, "")
        assert not type(mirrored).objects.filter(pk=mirrored.pk).exists()
        assert RevokedTeamSecretToken.objects.for_team(self.team.id).filter().exists()
        legacy_exposed.assert_called_once()

    @parameterized.expand([("personal", "personalapikey"), ("project_secret", "projectsecretapikey")])
    def test_an_old_roll_url_lands_on_the_panel_of_the_key_owner(self, kind: str, model_name: str) -> None:
        if kind == "personal":
            key: Model = self._personal_key()
            expected = f"/admin/console/users/{self.user.pk}/?from=ticket#panel-personal-api-keys"
        else:
            key, _ = create_project_secret_api_key(team=self.team, created_by=self.user)
            expected = f"/admin/console/teams/{self.team.pk}/?from=ticket#panel-secret-api-keys"

        response = self.client.post(f"/admin/posthog/{model_name}/{key.pk}/roll/?from=ticket")

        assert response.status_code == 302
        assert response["Location"] == expected


class TestAdminConsoleOAuthSessions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    @time_machine.travel("2026-01-01 00:00:00", tick=False)
    def test_revoking_sessions_previews_the_applications_then_revokes_their_tokens(self) -> None:
        app = OAuthApplication.objects.create(
            name="Revoke console app",
            client_id="revoke_console_client_id",
            client_secret="revoke_console_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )
        access_token = OAuthAccessToken.objects.create(
            application=app, user=self.user, token="at_revoke_console", expires=timezone.now() + timedelta(minutes=5)
        )
        OAuthRefreshToken.objects.create(
            application=app, user=self.user, token="rt_revoke_console", access_token=access_token
        )
        url = "/admin/console/tools/oauth-sessions/revoke/"

        form = self.client.get(url, {"application": str(app.id)})
        preview = self.client.post(url, {"applications": str(app.id), "reason": "Scopes narrowed"})

        assert form.context["form"].initial["applications"] == str(app.id)
        assert preview.status_code == 200
        assert "Revoke console app" in preview.content.decode()
        assert OAuthAccessToken.objects.filter(application=app).count() == 1

        confirmed = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert confirmed.status_code == 302
        assert OAuthAccessToken.objects.filter(application=app).count() == 0
        assert OAuthRefreshToken.objects.filter(application=app, revoked__isnull=True).count() == 0
