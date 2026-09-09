import dataclasses

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.cdp.migrations import coerce_input_value, migrate_legacy_plugins
from posthog.cdp.templates._siteapps.template_notification_bar import template as notification_bar
from posthog.cdp.templates._siteapps.template_pineapple_mode import template as pineapple_mode
from posthog.cdp.templates.helpers import mock_transpile
from posthog.cdp.templates.hog_function_template import sync_template_to_db

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.plugin import Plugin, PluginConfig, PluginSourceFile


class TestCoerceInputValue(BaseTest):
    @parameterized.expand(
        [
            ("boolean_yes", {"type": "boolean"}, "Yes", True),
            ("boolean_no", {"type": "boolean"}, "No", False),
            ("boolean_empty", {"type": "boolean"}, "", False),
            ("boolean_untouched", {"type": "boolean"}, True, True),
            ("boolean_unknown_string", {"type": "boolean"}, "maybe", "maybe"),
            ("string_from_number", {"type": "string"}, 999999, "999999"),
            ("string_untouched", {"type": "string"}, "sticky", "sticky"),
            ("choice_untouched", {"type": "choice"}, "Yes", "Yes"),
        ]
    )
    def test_coerce_input_value(self, _name, schema, value, expected):
        assert coerce_input_value(value, schema) == expected


class TestMigrateSiteApps(BaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(dataclasses.asdict(pineapple_mode))
        sync_template_to_db(dataclasses.asdict(notification_bar))

        self.plugin_config = self._create_site_app(
            "Pineapple Mode",
            "https://github.com/PostHog/pineapple-mode-app",
            {"emoji": "🍍", "intensity": "5", "showButton": "No", "startRaining": "Yes"},
            unset={"buttonText": "Rain!"},
        )

    def _create_site_app(self, name: str, url: str, config: dict, unset: dict | None = None) -> PluginConfig:
        config_schema = [{"key": key, "type": "string", "site": True} for key in config]
        config_schema += [
            {"key": key, "type": "string", "site": True, "default": v} for key, v in (unset or {}).items()
        ]

        plugin = Plugin.objects.create(
            organization=self.team.organization,
            name=name,
            plugin_type="custom",
            url=url,
            config_schema=config_schema,
        )
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        return PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config=config,
            web_token=f"token-{name}",
        )

    @patch("posthog.cdp.site_functions.transpile", side_effect=mock_transpile)
    def test_migrates_site_app_plugin_to_hog_function(self, mock_transpile_fn):
        migrate_legacy_plugins(dry_run=False, test_mode=False, kind="site_app")

        hog_function = HogFunction.objects.get(team=self.team)
        assert hog_function.type == "site_app"
        assert hog_function.template_id == "template-pineapple-mode"
        assert hog_function.enabled

        inputs = hog_function.inputs or {}
        assert inputs["emoji"]["value"] == "🍍"
        assert inputs["intensity"]["value"] == "5"
        # The team never set this, so the plugin schema default is what the site app was showing
        assert inputs["buttonText"]["value"] == "Rain!"
        # The plugin stored these as choice strings, the template reads them as booleans
        assert inputs["showButton"]["value"] is False
        assert inputs["startRaining"]["value"] is True

        self.plugin_config.refresh_from_db()
        assert not self.plugin_config.enabled

    @patch("posthog.cdp.site_functions.transpile", side_effect=mock_transpile)
    def test_migrates_notification_bar_custom_css(self, mock_transpile_fn):
        css = ".notification-bar { font-size: 16px }"
        notification_bar_config = self._create_site_app(
            "Notification Bar",
            "https://github.com/PostHog/notification-bar-app",
            {"notification": "Hello", "position": "sticky", "cssOverride": css},
        )

        migrate_legacy_plugins(dry_run=False, test_mode=False, kind="site_app")

        hog_function = HogFunction.objects.get(team=self.team, template_id="template-notification-bar")
        # Braces in the CSS must survive as literal text rather than compile as Hog placeholders
        assert (hog_function.inputs or {})["cssOverride"]["value"] == css
        assert css in (hog_function.transpiled or "")

        notification_bar_config.refresh_from_db()
        assert not notification_bar_config.enabled

    @patch("posthog.cdp.site_functions.transpile", side_effect=mock_transpile)
    def test_migration_is_idempotent(self, mock_transpile_fn):
        migrate_legacy_plugins(dry_run=False, test_mode=False, kind="site_app")
        PluginConfig.objects.filter(id=self.plugin_config.id).update(enabled=True)
        migrate_legacy_plugins(dry_run=False, test_mode=False, kind="site_app")

        assert HogFunction.objects.filter(team=self.team).count() == 1
