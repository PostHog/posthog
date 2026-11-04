import re
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import Client, SimpleTestCase

from parameterized import parameterized

from posthog.admin.console.panels import Operation, Owner, Panel
from posthog.admin.console.registry import ConsoleRegistry, console

from products.workflows.backend.facade.api import get_email_sending_state

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

    def test_every_panel_owner_crest_ships(self) -> None:
        missing = sorted(
            {
                panel.owner.crest
                for panel in console.panels_for("team")
                if not (CONSOLE_ASSETS / "crests" / f"{panel.owner.crest}.svg").is_file()
            }
        )

        assert not missing, f"Panel owners name crests the console does not ship: {missing}. Rebuild with `{REBUILD}`."

    def test_registering_a_second_panel_with_a_taken_key_fails(self) -> None:
        registry = ConsoleRegistry()
        registry.register_panel(type("FirstPanel", (_DuplicatePanel,), {}))

        with self.assertRaisesRegex(ValueError, "already used"):
            registry.register_panel(type("SecondPanel", (_DuplicatePanel,), {}))

    def test_a_danger_operation_without_a_reason_field_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason"):
            Operation(key="wipe", label="Wipe", handler=lambda request, obj, form: None, danger=True)


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
        for title in ("Overview", "Remote config cache", "Email sending"):
            assert title in content

    @parameterized.expand(
        [
            ("suspend_with_reason", "suspend", {"reason": "Bounce rate above 10%"}, 302, True),
            ("suspend_without_reason", "suspend", {"reason": "   "}, 400, False),
            ("operation_not_offered_in_this_state", "unsuspend", {}, 404, False),
        ]
    )
    @patch("posthog.admin.admins.team_admin.create_notification")
    @patch("posthog.admin.admins.team_admin.send_email_sending_suspended")
    def test_email_sending_operations_run_the_admin_view(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        expected_status: int,
        expect_suspended: bool,
        _send_email: object,
        _create_notification: object,
    ) -> None:
        response = self.client.post(f"/admin/console/teams/{self.team.pk}/email-sending/{operation_key}/", data)

        assert response.status_code == expected_status
        if expected_status == 302:
            assert response["Location"] == f"/admin/console/teams/{self.team.pk}/"
        state = get_email_sending_state(self.team.pk)
        assert (state is not None and state.suspended_at is not None) == expect_suspended
