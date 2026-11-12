import re
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import FunctionType
from urllib.parse import urlencode

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import ANY, MagicMock, patch

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import Group
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.cache import caches
from django.core.exceptions import PermissionDenied
from django.db.models import PROTECT, Model
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import URLResolver, resolve
from django.urls.exceptions import Resolver404
from django.urls.resolvers import RegexPattern
from django.utils import timezone
from django.utils.html import escape, format_html

from django_otp.plugins.otp_totp.models import TOTPDevice
from loginas import settings as la_settings
from parameterized import parameterized
from structlog.testing import capture_logs
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin import register_all_admin
from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.api_key_search_tool import ApiKeySearchForm
from posthog.admin.console.moved import MovedAction, MovedPage
from posthog.admin.console.organization_panels import BillingPanel, QuotaLimits
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Gate, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import ConsoleRegistry, console
from posthog.admin.console.results import (
    CACHE_ALIAS as RESULTS_CACHE_ALIAS,
    KEY_COOKIE,
    KEY_PREFIX as RESULTS_KEY_PREFIX,
    ResultCodec,
)
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
    Download,
    FieldGroup,
    Filters,
    Link,
    Links,
    Live,
    Notice,
    Page,
    Paging,
    Row,
    Secret,
    Stat,
    Stats,
    Table,
    ToolOperation,
)
from posthog.admin.console.urls import moved_url_patterns
from posthog.admin.console.user_panels import Impersonation, is_acting_as
from posthog.admin.console.views import _offered_operations
from posthog.csp_middleware import CSPMiddleware
from posthog.middleware import IMPERSONATION_READ_ONLY_SESSION_KEY, IMPERSONATION_REASON_SESSION_KEY
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_visibility_manager
from posthog.models.data_deletion_request import DataDeletionRequest, RequestType
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.project_secret_api_key import RevokedTeamSecretToken
from posthog.models.team.team import Team
from posthog.models.tophog.queries import TopHogFilterOptions
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.session.models import Session
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.test.api_keys import create_project_secret_api_key

from products.posthog_ai.backend.models.assistant import Conversation

from ee.billing.quota_limiting import QuotaResource
from ee.hogai.django_checkpoint.compaction import CompactionResult

TEMPLATE_DIR = Path(settings.BASE_DIR) / "posthog" / "templates" / "admin_console"
CONSOLE_ASSETS = Path(settings.BASE_DIR) / "frontend" / "public" / "admin-console"
REBUILD = "pnpm --filter=@posthog/frontend build:admin-console"

_CLASS_ATTRIBUTE = re.compile(r'class="([^"]*)"')
_TEMPLATE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
_PATH_PARAMETER = re.compile(r"<(?:(\w+):)?(\w+)>")
_SAMPLE_VALUES = {"int": "7", "uuid": "0d7b8a52-4f0e-4b8e-9a43-6f1c2e5d9b10", "str": "example", "path": "example"}
CONSOLE_HOME = "/admin/console/"
TOOLS_PREFIX = "/admin/console/tools/"
# Old URLs that take over a Django admin view on purpose, because the console adds a reason and cleanup the raw
# view skips. Each ModelAdmin also refuses its raw view by permission, so the view stays closed when the moved
# routes are missing.
INTENTIONAL_ADMIN_OVERRIDES = frozenset(
    {
        "admin/posthog/user/<int:pk>/delete/",
        "admin/legal_documents/legaldocument/<path:object_id>/delete/",
        "admin/posthog/datadeletionrequest/add/",
        "admin/account_audits/accountauditcredential/add/",
        "admin/managed_warehouse/managedwarehouseviewtranslationjob/add/",
    }
)
# Django's set-password form. UserAdmin sets change_password_form to None, so the raw view never shows a form.
DISABLED_ADMIN_FORMS = frozenset({"admin/posthog/user/<int:pk>/password/"})


def _selector_present(css: str, class_name: str) -> bool:
    # Tailwind and quill escape every character that is not selector-safe, so `@3xl:grid-cols-2` is
    # written `.\@3xl\:grid-cols-2`. The trailing guard stops `.flex` matching inside `.flex-1`.
    escaped = "".join(char if char.isalnum() or char in "-_" else "\\" + char for char in class_name)
    return re.search(re.escape("." + escaped) + r"(?![a-zA-Z0-9_\\-])", css) is not None


def _sample_path(old_path: str) -> tuple[str, dict[str, str]]:
    # Fills each path parameter of an old URL pattern with a value its converter accepts.
    values: dict[str, str] = {}

    def fill(match: re.Match[str]) -> str:
        values[match.group(2)] = _SAMPLE_VALUES[match.group(1) or "str"]
        return values[match.group(2)]

    return "/" + _PATH_PARAMETER.sub(fill, old_path), values


class _DuplicatePanel(Panel):
    record = "team"
    key = "overview"
    title = "Duplicate"
    owner = Owner(name="Dev experience", crest="dev-experience")


class _UndeclaredOperationPanel(_DuplicatePanel):
    operation_keys = frozenset({"rebuild"})

    def operations(self, obj: Model) -> list[Operation]:
        return [Operation(key="rebuild-all", label="Rebuild all", handler=lambda request, obj, form: None)]


class _Tool(ConsoleTool):
    key = "some-report"
    title = "Some report"
    owner = Owner(name="Dev experience", crest="dev-experience")
    group = "Data"


class _ToolActionForm(forms.Form):
    reason = forms.CharField()
    confirm = forms.CharField(required=False)


class _ToolFiltersForm(forms.Form):
    since = forms.CharField()
    step = forms.CharField(widget=forms.HiddenInput, required=False)


class _ActingTool(_Tool):
    key = "acting-tool"
    title = "Acting tool"
    runs: list[str] = []

    def _act(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
        assert form is not None
        if form.cleaned_data["confirm"] != "yes":
            messages.error(request, "Type yes to confirm.")
            return HttpResponse(status=400)
        self.runs.append(form.cleaned_data["reason"])
        return None

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        if request.GET.get("state") == "stale":
            return []
        return [
            ToolOperation(
                key="act", label="Act", handler=self._act, form_class=_ToolActionForm, pending_label="Acting..."
            )
        ]

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(text="Check the window first.", tone=Tone.WARNING),
                Stats(items=(Stat(label="Runs to replay", value="1,234"),)),
                Links(
                    items=(
                        Link(label="Show details", href="/admin/console/", primary=True, pending_label="Loading..."),
                    )
                ),
                Filters(
                    form=_ToolFiltersForm(request.GET),
                    groups=(FieldGroup(title="Window", field_names=("since",)),),
                    submit_label="Preview",
                ),
            )
        )


class _SecretTool(_Tool):
    key = "issue-password"
    runs = 0

    def page(self, request: HttpRequest) -> Page:
        return Page(blocks=())

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="issue",
                label="Issue a password",
                handler=self.issue,
                danger=True,
                form_class=ReasonForm,
                undo_hint="Rotate the password.",
            )
        ]

    @classmethod
    def issue(cls, request: HttpRequest, form: object) -> Page:
        cls.runs += 1
        return Page(
            blocks=(
                Stats(items=(Stat(label="Passwords issued", value="1"),)),
                Secret(label="Root password", value="example-secret-value"),
                Links(items=(Link(label="Back to the cluster", href="/admin/console/"),)),
            )
        )


def _register_twice() -> None:
    registry = ConsoleRegistry()
    registry.register_panel(type("FirstPanel", (_DuplicatePanel,), {}))
    registry.register_panel(type("SecondPanel", (_DuplicatePanel,), {}))


def _fresh_resolver() -> Callable[..., None]:
    # A new function object each call, as when a module that failed to import runs again.
    def find_team(key_id: str) -> None:
        return None

    return find_team


def _assert_target_is_registered(moved: MovedAction) -> None:
    # A target is a panel anchor such as "#panel-remote-config", or an operation form such as "api-token/set/".
    page, _, anchor = moved.target.partition("#")
    panel_key, _, operation_path = (anchor.removeprefix("panel-") if anchor else page).partition("/")
    panel = console.get_panel(moved.record, panel_key)
    assert panel is not None, f"{moved.old_path} leads to {moved.record} panel {panel_key!r}, which is not registered"
    operation_key = operation_path.strip("/")
    if operation_key:
        assert panel.operation_keys is not None and operation_key in panel.operation_keys, (
            f"{moved.old_path} leads to operation {operation_key!r}, which {type(panel).__name__}.operation_keys "
            "does not declare"
        )


def _move_twice() -> None:
    registry = ConsoleRegistry()
    registry.register_moved_page(old_path="admin/report/", title="Report", url="/admin/console/tools/report/")
    registry.register_moved_page(old_path="admin/report/", title="Report", url="/admin/console/tools/other-report/")


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
                "moved_url_outside_the_admin_step_up",
                lambda: ConsoleRegistry().register_moved_page(
                    old_path="resave-cohorts/", title="Re-save cohorts", url="/admin/console/tools/resave-cohorts/"
                ),
                "under admin/",
            ),
            (
                "moved_action_without_a_way_to_find_its_record",
                lambda: ConsoleRegistry().register_moved_action(
                    old_path="admin/posthog/team/<int:team_id>/rebuild-cache/", record="team", target="#panel-x"
                ),
                "needs a <pk>",
            ),
            ("moved_url_registered_by_two_contributions", _move_twice, "already registered"),
            (
                "operation_missing_from_operation_keys",
                lambda: _offered_operations(_UndeclaredOperationPanel(), Team()),
                "missing from operation_keys",
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
                "danger_tool_operation_without_reason",
                lambda: ToolOperation(
                    key="wipe",
                    label="Wipe",
                    handler=lambda request, form: None,
                    form_class=forms.Form,
                    danger=True,
                    undo_hint="It cannot be undone.",
                ),
                "reason",
            ),
            (
                "link_off_site",
                lambda: Link(label="Docs", href="//example.com/phish"),
                "starts with /",
            ),
            (
                "filters_that_would_hide_a_field",
                lambda: Filters(
                    form=_ToolActionForm(),
                    groups=(FieldGroup(title="Only one", field_names=("reason",)),),
                    submit_label="Go",
                ),
                "must name each form field",
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
                "notice_linking_off_site_with_a_backslash",
                lambda: Notice(text="Moved", link_text="Open", href="/\\example.com/phish"),
                "starts with /",
            ),
            (
                "link_off_site_with_a_tab_the_browser_drops",
                lambda: Link(label="Docs", href="/\t/example.com/phish"),
                "starts with /",
            ),
            (
                "fact_linking_off_site_with_a_newline_the_browser_drops",
                lambda: Fact(label="Docs", value="Read", href="/\n/example.com/phish"),
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
                "not a table, notice, output or stats",
            ),
            (
                "live_block_holding_a_secret",
                lambda: Live(key="password", block=Secret(label="Root password", value="example")),  # type: ignore[arg-type]
                "not a table, notice, output or stats",
            ),
            (
                "secret_on_a_page_that_renders_again",
                lambda: Page(blocks=(Secret(label="Password", value="x"),)).refuse_secrets("tool page"),
                "only from an operation's result page",
            ),
            (
                "table_row_missing_a_cell",
                lambda: Page(blocks=(Table(columns=("Team", "Months"), rows=(Row(cells=(Cell(text="a"),)),)),)),
                "1 cells for 2 columns",
            ),
            (
                "download_name_that_would_break_the_header",
                lambda: Download(filename='certificate".json', content_type="application/json", content="{}"),
                "only letters",
            ),
        ]
    )
    def test_the_console_contract_refuses_a_contribution_that_would_render_wrong(
        self, _name: str, contribute: Callable[[], object], message: str
    ) -> None:
        with self.assertRaisesRegex(ValueError, message):
            contribute()

    def test_a_contribution_module_that_runs_again_registers_the_same_declarations_again(self) -> None:
        registry = ConsoleRegistry()

        for _ in range(2):
            registry.register_panel(type("RetriedPanel", (_DuplicatePanel,), {}))
            registry.register_moved_action(
                old_path="admin/posthog/apikey/<str:key_id>/roll/",
                record="team",
                target="#panel-overview",
                resolver=_fresh_resolver(),
            )

        assert type(registry.get_panel("team", "overview")).__name__ == "RetriedPanel"
        assert [moved.old_path for moved in registry.moved()] == ["admin/posthog/apikey/<str:key_id>/roll/"]

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


def _shared_console() -> None:
    registry.register_moved_page(old_path="admin/shared/", title="Shared", url="/admin/console/tools/shared/")  # type: ignore[name-defined]  # noqa: F821


def _broken_console() -> None:
    # Imports a healthy module before it raises, so the test checks that the rollback keeps what that one declared.
    import_module("products.shared.backend.console")
    registry.register_moved_page(old_path="admin/broken/", title="Broken", url="/admin/console/tools/broken/")  # type: ignore[name-defined]  # noqa: F821
    raise RuntimeError("a console.py raised")


def _working_console() -> None:
    registry.register_moved_page(old_path="admin/report/", title="Report", url="/admin/console/tools/report/")  # type: ignore[name-defined]  # noqa: F821


FAKE_CONSOLE_MODULES = {
    "products.shared.backend.console": _shared_console,
    "products.broken.backend.console": _broken_console,
    "products.working.backend.console": _working_console,
}


class TestAdminConsoleMovedUrls(SimpleTestCase):
    def _get(self, url: str) -> HttpResponse:
        request = RequestFactory().get(url)
        request.user = User(email="staff@posthog.com", is_staff=True, is_active=True)
        request._messages = CookieStorage(request)  # type: ignore[attr-defined]
        match = resolve(request.path)
        return match.func(request, *match.args, **match.kwargs)

    def test_a_contribution_that_raises_drops_only_its_own_moved_urls(self) -> None:
        registry = ConsoleRegistry()
        imported: set[str] = set()

        def import_contribution(module_name: str) -> None:
            if module_name in imported:
                return
            imported.add(module_name)
            # The function runs with the fake module's __name__, as a real console.py would, so the registry sees
            # which module declared each moved URL.
            module_globals = {"__name__": module_name, "registry": registry, "import_module": import_contribution}
            FunctionType(FAKE_CONSOLE_MODULES[module_name].__code__, module_globals)()

        with (
            patch.object(
                registry,
                "contribution_modules",
                return_value=[
                    "products.broken.backend.console",
                    "products.shared.backend.console",
                    "products.working.backend.console",
                ],
            ),
            patch("posthog.admin.console.registry.importlib.import_module", side_effect=import_contribution),
            capture_logs() as logs,
        ):
            urlconf = URLResolver(RegexPattern(r"^/"), moved_url_patterns(registry))

        assert urlconf.resolve("/admin/report/").route == "admin/report/"
        # The broken module imported the shared one before raising: the shared declaration stays, the broken one goes.
        assert sorted(moved.old_path for moved in registry.moved()) == ["admin/report/", "admin/shared/"]
        assert [(log["event"], log["module"]) for log in logs] == [
            ("admin_console_contribution_failed", "products.broken.backend.console")
        ]

    @parameterized.expand(
        [
            (moved.old_path, moved)
            for moved in console.moved()
            if isinstance(moved, MovedAction) and moved.resolver is None
        ]
    )
    def test_an_old_action_url_lands_on_its_registered_panel(self, _name: str, moved: MovedAction) -> None:
        old_path, values = _sample_path(moved.old_path)

        response = self._get(f"{old_path}?from=ticket")

        page, _, anchor = moved.target.partition("#")
        record_page = f"/admin/console/{RECORD_TYPES[moved.record].plural}/{values['pk']}/"
        assert response.status_code == 302
        assert response["Location"] == f"{record_page}{page}?from=ticket" + (f"#{anchor}" if anchor else "")
        _assert_target_is_registered(moved)

    @parameterized.expand(
        [
            (moved.old_path, moved)
            for moved in console.moved()
            if isinstance(moved, MovedAction) and moved.resolver is not None
        ]
    )
    def test_an_old_action_url_with_a_resolver_routes_to_its_registered_panel(
        self, _name: str, moved: MovedAction
    ) -> None:
        old_path, _ = _sample_path(moved.old_path)

        # A resolver looks its record up in the database, so its product tests cover where the redirect lands.
        assert resolve(old_path).route == moved.old_path
        _assert_target_is_registered(moved)

    @parameterized.expand([(moved.old_path, moved) for moved in console.moved()])
    def test_an_old_url_replaces_no_live_django_admin_view(self, _name: str, moved: MovedAction | MovedPage) -> None:
        register_all_admin()
        django_admin = URLResolver(RegexPattern(r"^/admin/"), admin.site.get_urls())
        old_path, _ = _sample_path(moved.old_path)

        try:
            route = django_admin.resolve(old_path).route
        except Resolver404:
            return
        # Django admin answers every unknown path with a redirect to the change page or the catch-all 404 view.
        catch_all = route.endswith("<path:object_id>/") or route == "(?P<url>.*)$"
        assert catch_all or moved.old_path in INTENTIONAL_ADMIN_OVERRIDES | DISABLED_ADMIN_FORMS, (
            f"{moved.old_path} hides the live Django admin route {route!r}. Remove that view first, or add the "
            "path to INTENTIONAL_ADMIN_OVERRIDES when the console replaces it on purpose."
        )

    @parameterized.expand([(moved.old_path, moved) for moved in console.moved() if isinstance(moved, MovedPage)])
    def test_an_old_page_url_lands_on_its_registered_tool(self, _name: str, moved: MovedPage) -> None:
        old_path, values = _sample_path(moved.old_path)

        response = self._get(f"{old_path}?from=ticket")

        target = moved.url.format(**values)
        assert response.status_code == 302
        assert response["Location"] == target + ("&" if "?" in target else "?") + "from=ticket"
        if target == CONSOLE_HOME:
            return
        tool_key = target.removeprefix(TOOLS_PREFIX).split("/")[0]
        assert target.startswith(TOOLS_PREFIX) and console.get_tool(tool_key) is not None, f"No tool for {target}"


class TestAdminConsoleOverriddenAdminViews(BaseTest):
    @parameterized.expand([(old_path,) for old_path in sorted(INTENTIONAL_ADMIN_OVERRIDES)])
    def test_django_admin_refuses_the_raw_view_an_old_url_overrides(self, old_path: str) -> None:
        register_all_admin()
        django_admin = URLResolver(RegexPattern(r"^/admin/"), admin.site.get_urls())
        sample_path, _ = _sample_path(old_path)
        match = django_admin.resolve(sample_path)
        request = RequestFactory().get(sample_path)
        self.user.is_staff = True
        request.user = self.user

        with self.assertRaises(PermissionDenied):
            match.func(request, *match.args, **match.kwargs)


class TestAdminConsoleFormField(SimpleTestCase):
    @parameterized.expand(
        [
            ("password_input_hides_the_key", "key", False),
            ("text_input_keeps_what_staff_typed", "note", True),
        ]
    )
    def test_a_form_shown_again_after_an_error_keeps_secrets_out(
        self, _name: str, field_name: str, value_shown: bool
    ) -> None:
        class _KeyForm(ApiKeySearchForm):
            note = forms.CharField()

        form = _KeyForm(data={"key": "phx_pasted_secret_key", "note": "typed note"})
        form.is_valid()
        form.add_error(field_name, "Not found.")

        html = render_to_string("admin_console/_form_field.html", {"field": form[field_name]})

        assert "Not found." in html
        assert ("phx_pasted_secret_key" in html or "typed note" in html) == value_shown


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

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_a_secret_result_shows_once_and_a_reload_does_not_run_the_operation_again(self) -> None:
        _SecretTool.runs = 0
        with patch.object(console, "get_tool", return_value=_SecretTool()), capture_logs() as audit_log:
            response = self.client.post("/admin/console/tools/issue-password/issue/", {"reason": "Customer onboarding"})
            result_id = response["Location"].rstrip("/").rsplit("/", 1)[-1]
            cached = repr(caches[RESULTS_CACHE_ALIAS].get(f"{RESULTS_KEY_PREFIX}:{result_id}"))
            key_cookie = response.cookies[KEY_COOKIE]
            first = self.client.get(response["Location"])
            reload = self.client.get(response["Location"])

        assert response.status_code == 302
        assert response["Location"].startswith("/admin/console/results/")
        assert "example-secret-value" not in response["Location"]
        assert "example-secret-value" not in cached and key_cookie.value not in cached
        assert key_cookie["path"] == response["Location"] and key_cookie["httponly"] and key_cookie["secure"]
        assert key_cookie["samesite"] == "Strict"
        assert first.cookies[KEY_COOKIE]["max-age"] == 0
        assert first.status_code == 200
        assert "example-secret-value" in first.content.decode()
        assert "Passwords issued" in first.content.decode() and "Back to the cluster" in first.content.decode()
        assert reload.status_code == 410
        assert "example-secret-value" not in reload.content.decode()
        assert _SecretTool.runs == 1
        for page in (response, first, reload):
            assert "no-store" in page["Cache-Control"]
        assert any(entry.get("reason") == "Customer onboarding" for entry in audit_log)
        assert "example-secret-value" not in repr(audit_log)

    @parameterized.expand(
        [
            ("without_its_key", None, 410, "The key for this result is missing", True),
            ("stored_by_another_version", KeyError("RenamedBlock"), 410, "PostHog was updated", False),
        ]
    )
    def test_a_result_that_cannot_be_opened_explains_why(
        self, _name: str, decode_error: Exception | None, status: int, explanation: str, kept: bool
    ) -> None:
        with patch.object(console, "get_tool", return_value=_SecretTool()):
            response = self.client.post("/admin/console/tools/issue-password/issue/", {"reason": "Customer onboarding"})
        result_id = response["Location"].rstrip("/").rsplit("/", 1)[-1]
        if decode_error is None:
            self.client.cookies.pop(KEY_COOKIE)
        with patch.object(ResultCodec, "loads", side_effect=decode_error):
            page = self.client.get(response["Location"])

        assert page.status_code == status
        assert explanation in page.content.decode()
        assert "example-secret-value" not in page.content.decode()
        assert (caches[RESULTS_CACHE_ALIAS].get(f"{RESULTS_KEY_PREFIX}:{result_id}") is not None) == kept

    def _record(self, record: str) -> Model:
        if record == "deletion-request":
            return DataDeletionRequest.objects.create(team_id=self.team.pk, request_type=RequestType.EVENT_REMOVAL)
        return {"team": self.team, "organization": self.organization, "project": self.project, "user": self.user}[
            record
        ]

    @parameterized.expand([(record,) for record in RECORD_TYPES])
    def test_every_registered_panel_renders_on_its_record_page(self, record: str) -> None:
        obj = self._record(record)

        response = self.client.get(RECORD_TYPES[record].url(obj))

        assert response.status_code == 200
        content = response.content.decode()
        for panel in console.panels_for(record):
            assert escape(panel.title) in content, f"{panel.key} is missing from the {record} page"
            assert len(panel.facts(obj)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"

    def test_record_pages_link_their_related_records(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        content = self.client.get(f"/admin/console/teams/{self.team.pk}/").content.decode()

        assert "Needs attention" in content and "Ingested events:" in content
        assert f"/admin/console/organizations/{self.organization.pk}/" in content
        assert f"/admin/console/projects/{self.project.pk}/" in content
        assert f"/admin/console/users/{self.user.pk}/" in content
        organization_content = self.client.get(f"/admin/console/organizations/{self.organization.pk}/").content
        assert f"/admin/console/teams/{self.team.pk}/" in organization_content.decode()
        for record_page in (f"/admin/console/projects/{self.project.pk}/", f"/admin/console/users/{self.user.pk}/"):
            assert (
                f"/admin/console/organizations/{self.organization.pk}/" in self.client.get(record_page).content.decode()
            )
        assert (
            f"/admin/console/teams/{self.team.pk}/"
            in self.client.get(f"/admin/console/projects/{self.project.pk}/").content.decode()
        )

        home = self.client.get("/admin/console/").content.decode()
        assert "Recently opened" in home
        assert f"/admin/console/teams/{self.team.pk}/" in home

    @parameterized.expand([("team",), ("project",), ("user",)])
    def test_django_admin_page_points_moved_actions_to_registered_panels(self, record: str) -> None:
        obj = self._record(record)

        response = self.client.get(f"/admin/posthog/{record}/{obj.pk}/change/")

        assert response.status_code == 200
        content = response.content.decode()
        assert "This is the Django admin" in content
        panel_keys = re.findall(rf"/admin/console/{record}s/{obj.pk}/#panel-([a-z0-9-]+)", content)
        assert panel_keys, f"The Django admin {record} page points nowhere in the console"
        unknown = sorted(key for key in set(panel_keys) if console.get_panel(record, key) is None)
        assert not unknown, f"The Django admin {record} page points to panels the console does not have: {unknown}"

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

    @parameterized.expand(
        [
            ("team_name", "team", None),
            ("team_uuid", "team_uuid", None),
            ("team_api_token_in_uuid_form", "team_token", None),
            ("organization_id", "organization", None),
            ("user_email_in_another_case", "user", None),
            ("user_email_from_a_support_ticket", "user", "https://support.example.com/tickets/42"),
        ]
    )
    def test_a_lookup_with_one_match_opens_its_page(self, _name: str, record: str, ticket: str | None) -> None:
        if record == "team":
            query, expected = self.team.name, f"/admin/console/teams/{self.team.pk}/"
        elif record == "team_uuid":
            query, expected = str(self.team.uuid), f"/admin/console/teams/{self.team.pk}/"
        elif record == "team_token":
            query, expected = "3f2b8c1e-5d47-4a90-b6e2-9c0d1f7a8e35", f"/admin/console/teams/{self.team.pk}/"
            Team.objects.filter(pk=self.team.pk).update(api_token=query)
        elif record == "organization":
            query, expected = str(self.organization.pk), f"/admin/console/organizations/{self.organization.pk}/"
        else:
            query, expected = self.user.email.upper(), f"/admin/console/users/{self.user.pk}/"
        params = {"q": query, **({"ticket": ticket} if ticket else {})}
        kept = f"?{urlencode({'ticket': ticket})}" if ticket else ""

        response = self.client.get("/admin/console/", params)

        assert response.status_code == 302
        assert response["Location"] == expected + kept

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

    @parameterized.expand(
        [
            ("runs_and_keeps_the_query", "?window=1", {"reason": "outage", "confirm": "yes"}, 302, ["outage"]),
            ("handler_refusal_keeps_what_staff_typed", "", {"reason": "kept text", "confirm": "no"}, 400, []),
            ("invalid_form_runs_nothing", "", {"reason": "", "confirm": "yes"}, 400, []),
            ("operation_the_tool_no_longer_offers", "?state=stale", {"reason": "late", "confirm": "yes"}, 404, []),
        ]
    )
    def test_a_tool_operation_runs_only_when_offered_and_valid(
        self, _name: str, query: str, data: dict[str, str], status: int, runs: list[str]
    ) -> None:
        _ActingTool.runs = []
        with patch.object(console, "get_tool", return_value=_ActingTool()):
            response = self.client.post(f"/admin/console/tools/acting-tool/act/{query}", data)

        assert response.status_code == status
        assert _ActingTool.runs == runs
        if status == 302:
            assert response["Location"] == f"/admin/console/tools/acting-tool/{query}"
        if data["reason"] == "kept text":
            content = response.content.decode()
            assert "Type yes to confirm." in content
            assert 'value="kept text"' in content
            assert 'data-pending-label="Acting..."' in content

    def test_a_tool_page_renders_every_block_it_holds(self) -> None:
        with patch.object(console, "get_tool", return_value=_ActingTool()):
            response = self.client.get("/admin/console/tools/acting-tool/?since=2026-10-22&step=details")

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-tone="warning"' in content and "Check the window first." in content
        assert "Runs to replay" in content and "1,234" in content
        assert 'data-pending-label="Loading..."' in content and "Show details" in content
        assert 'value="2026-10-22"' in content and "Preview" in content
        assert re.search(r'<input type="hidden" name="step" value="details"', content)

    def test_a_tool_operation_needs_a_csrf_token_even_with_an_api_key_parameter(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        _ActingTool.runs = []

        with patch.object(console, "get_tool", return_value=_ActingTool()):
            response = client.post(
                "/admin/console/tools/acting-tool/act/?personal_api_key=phx_example",
                {"reason": "forged", "confirm": "yes"},
            )

        assert response.status_code == 403
        assert _ActingTool.runs == []

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
    @patch("posthog.admin.console.organization_deletion_panels.report_organization_deleted")
    @patch("posthog.admin.console.organization_deletion_panels.start_delete_organization_workflow")
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
            ("compacted", CompactionResult(compacted=True, checkpoints_deleted=3, blobs_deleted=5)),
            ("nothing_to_compact", CompactionResult(compacted=False)),
        ]
    )
    @patch("posthog.admin.console.conversation_checkpoints_tool.compact_conversation")
    def test_compacting_conversations_previews_then_runs_on_confirm(
        self, _name: str, result: CompactionResult, compact: MagicMock
    ) -> None:
        compact.return_value = result
        ids = [str(Conversation.objects.create(team=self.team, user=self.user).id) for _ in range(2)]
        url = "/admin/console/tools/ai-conversation-checkpoints/compact/"

        preview = self.client.post(url, {"conversations": "\n".join(ids), "reason": "Threads too large to load"})

        assert preview.status_code == 200
        assert compact.call_count == 0
        preview_content = preview.content.decode()
        assert all(conversation_id in preview_content for conversation_id in ids)
        assert "Deletes up to 0 checkpoints" in preview_content

        confirmed = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert confirmed.status_code == 302
        assert compact.call_count == 2

    @patch("posthog.admin.console.conversation_checkpoints_tool.compact_conversation")
    def test_compaction_preview_refuses_an_unknown_conversation(self, compact: MagicMock) -> None:
        known = str(Conversation.objects.create(team=self.team, user=self.user).id)
        unknown = "01920000-0000-0000-0000-000000000000"

        response = self.client.post(
            "/admin/console/tools/ai-conversation-checkpoints/compact/",
            {"conversations": f"{known}\n{unknown}", "reason": "Threads too large to load"},
        )

        assert response.status_code == 400
        assert unknown in response.content.decode()
        compact.assert_not_called()

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

        with capture_logs() as logs:
            response = self.client.post(
                f"/admin/console/tools/tophog/extend-{restriction.pk}/"
                "?token=phc_tophog&distinct_id=new-id&pipelines=sessionreplay&team_id=7",
                data,
            )

        assert response.status_code == expected_status
        if expected_status == 302:
            started = next(log for log in logs if log["event"] == "admin_console_operation_started")
            assert started["query"] == {
                "token": "phc_tophog",
                "distinct_id": "<not logged>",
                "pipelines": "sessionreplay",
                "team_id": "7",
            }
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
            ("team_change_form", "team", "teams", []),
            (
                "organization_change_form_suggests_deactivation_reasons",
                "organization",
                "organizations",
                [
                    'list="id_is_not_active_reason_suggestions"',
                    f'<option value="{Organization.DeactivationReason.DESKTOP_ABUSE}">',
                ],
            ),
            ("changelist", None, None, []),
        ]
    )
    def test_the_django_admin_banner_opens_the_console_page_of_the_record(
        self, _name: str, record: str | None, plural: str | None, expected: list[str]
    ) -> None:
        obj = {"team": self.team, "organization": self.organization}.get(record or "")
        url = f"/admin/posthog/{record}/{obj.pk}/change/" if obj is not None else "/admin/posthog/team/"

        response = self.client.get(url)

        assert response.status_code == 200
        console_url = f"/admin/console/{plural}/{obj.pk}/" if obj is not None else "/admin/console/"
        content = response.content.decode()
        assert f'<a href="{console_url}">Open PostHog Admin</a>' in content
        for text in expected:
            assert text in content

    @parameterized.expand(
        [
            (
                "values_list_the_matching_keys",
                "/admin/redisvalues?q=cache:*",
                "/admin/console/tools/redis-values/?q=cache:*",
                ["cache:key", "x" * 200 + "...", "Next keys", "1:00:00"],
            ),
            (
                "edit_ttl_opens_the_form_for_the_key",
                "/admin/redis/edit-ttl?key=cache:key&c=0",
                "/admin/console/tools/redis-values/set-ttl/?key=cache:key&c=0",
                ['value="cache:key"', 'value="3600"'],
            ),
        ]
    )
    @patch("posthog.admin.console.redis_tool.get_client")
    def test_the_old_redis_pages_open_the_redis_tool(
        self, _name: str, old_url: str, new_url: str, expected: list[str], get_client: MagicMock
    ) -> None:
        redis_client = get_client.return_value
        redis_client.scan.return_value = (5, [b"cache:key"])
        redis_client.type.return_value = b"string"
        redis_client.ttl.return_value = 3600
        redis_client.memory_usage.return_value = 300
        redis_client.get.return_value = "x" * 300

        response = self.client.get(old_url, follow=True)

        assert response.redirect_chain == [(new_url, 302)]
        content = response.content.decode()
        for text in expected:
            assert text in content

    @patch("posthog.admin.console.redis_tool.get_client")
    def test_the_redis_tool_shows_the_whole_value_of_one_key(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.type.return_value = b"string"
        redis_client.ttl.return_value = -1
        redis_client.memory_usage.return_value = 300
        redis_client.get.return_value = "x" * 300

        response = self.client.get("/admin/console/tools/redis-values/", {"key": "cache:key"})

        content = response.content.decode()
        assert "x" * 300 in content
        assert "No TTL" in content

    @parameterized.expand(
        [
            ("set", 3600, "7200", 302, "ttl_updated", "Set TTL to 7200s on Redis key cache:key"),
            ("remove", 3600, "", 302, "ttl_removed", "Removed TTL from Redis key cache:key"),
            ("missing_key", -2, "7200", 404, None, None),
            ("without_reason", 3600, "7200", 400, None, None),
            ("ttl_too_large", 3600, str(10**12), 400, None, None),
        ]
    )
    @patch("posthog.admin.console.redis_tool.get_client")
    def test_setting_a_redis_ttl_changes_the_key_and_logs_who_did_it(
        self,
        name: str,
        current_ttl: int,
        ttl_seconds: str,
        expected_status: int,
        expected_activity: str | None,
        expected_detail: str | None,
        get_client: MagicMock,
    ) -> None:
        redis_client = get_client.return_value
        redis_client.ttl.return_value = current_ttl

        response = self.client.post(
            "/admin/console/tools/redis-values/set-ttl/?key=cache:key",
            {"key": "cache:key", "ttl_seconds": ttl_seconds, "reason": "" if name == "without_reason" else "Stuck"},
        )

        assert response.status_code == expected_status
        logs = ActivityLog.objects.filter(scope="Admin", item_id="cache:key")
        if expected_activity is None:
            redis_client.expire.assert_not_called()
            redis_client.persist.assert_not_called()
            assert not logs.exists()
            return
        assert response["Location"] == "/admin/console/tools/redis-values/?key=cache:key"
        if ttl_seconds:
            redis_client.expire.assert_called_once_with("cache:key", int(ttl_seconds))
        else:
            redis_client.persist.assert_called_once_with("cache:key")
        log = logs.get()
        assert (log.activity, log.user, log.organization_id) == (expected_activity, self.user, self.organization.id)
        assert log.detail is not None
        assert log.detail["name"] == expected_detail
        assert log.detail["type"] == f"previous_ttl:{current_ttl}"
        assert log.detail["context"] == {"reason": "Stuck"}
        assert activity_visibility_manager.is_restricted(log, restrict_for_staff=True)


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


class TestAdminConsoleLogInAsUser(BaseTest):
    ticket = "https://support.example.com/tickets/42"

    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.target = User.objects.create_and_join(self.organization, "impersonation-target@example.com", None)
        self.url = f"/admin/console/users/{self.target.pk}/log-in-as/log-in/"

    @parameterized.expand([("read_only", {"read_only": "on"}, True), ("read_and_write", {}, False)])
    def test_logging_in_starts_the_impersonation_in_the_chosen_mode(
        self, _name: str, mode: dict[str, str], read_only: bool
    ) -> None:
        response = self.client.post(self.url, {"reason": "For ticket 42", **mode})

        assert response.status_code == 302
        assert response["Location"] == la_settings.LOGIN_REDIRECT
        session = self.client.session
        assert session[SESSION_KEY] == str(self.target.pk)
        assert session.get(IMPERSONATION_READ_ONLY_SESSION_KEY, False) == read_only
        assert session[IMPERSONATION_REASON_SESSION_KEY] == "For ticket 42"

    @parameterized.expand(
        [
            ("blank_reason", {}, {"reason": " "}, False, 400),
            ("staff_target", {"is_staff": True}, {"reason": "For ticket 42"}, False, 404),
            ("target_turned_it_off", {"allow_impersonation": False}, {"reason": "For ticket 42"}, False, 404),
            # CAN_LOGIN_AS still refuses when the panel offers the operation by mistake.
            ("staff_target_offered_by_mistake", {"is_staff": True}, {"reason": "For ticket 42"}, True, 302),
        ]
    )
    def test_refused_log_in_leaves_the_staff_session_alone(
        self, _name: str, target_state: dict[str, bool], data: dict[str, str], offered: bool, expected_status: int
    ) -> None:
        User.objects.filter(pk=self.target.pk).update(**target_state)

        with patch.object(Impersonation, "refusal", return_value=None) if offered else nullcontext():
            response = self.client.post(self.url, data)

        assert response.status_code == expected_status
        assert self.client.session[SESSION_KEY] == str(self.user.pk)

    def test_a_support_ticket_fills_in_the_reason(self) -> None:
        record_page = self.client.get(f"/admin/console/users/{self.target.pk}/", {"ticket": self.ticket})
        operation_url = f"{self.url}?{urlencode({'ticket': self.ticket})}"
        assert f'href="{escape(operation_url)}"' in record_page.content.decode()

        form = self.client.get(operation_url).context["form"]

        assert form["reason"].value() == f"For ticket {self.ticket}"
        assert form["read_only"].value() is True


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
