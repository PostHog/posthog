from posthog.test.base import BaseTest

from posthog.cdp.legacy_destination_migration import disable_migrated_plugin_configs, migrate_legacy_destinations

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType
from products.cdp.backend.models.plugin import Plugin, PluginAttachment, PluginConfig


class TestLegacyDestinationMigration(BaseTest):
    def setUp(self):
        super().setUp()
        self.template = HogFunctionTemplate.objects.create(
            template_id="plugin-customerio-plugin",
            sha="1",
            name="Customer.io",
            description="Legacy Customer.io",
            code="",
            inputs_schema=[
                {"key": "customerioSiteId", "type": "string"},
                {"key": "mappings", "type": "json"},
            ],
            type="legacy_destination",
        )

    def _plugin(self, url="https://github.com/PostHog/customerio-plugin", methods=None):
        plugin, _ = Plugin.objects.get_or_create(
            url=url,
            defaults={
                "organization": self.organization,
                "name": "Customer.io",
                "plugin_type": "custom",
            },
        )
        plugin.capabilities = {"methods": methods if methods is not None else ["onEvent"]}
        plugin.save()
        return plugin

    def _migrate(self, dry_run=False, drop_unmapped_inputs=True):
        return migrate_legacy_destinations(
            dry_run=dry_run, team_ids=[self.team.id], drop_unmapped_inputs=drop_unmapped_inputs
        )

    def _hog_functions(self):
        return HogFunction.objects.filter(team=self.team, type=HogFunctionType.LEGACY_DESTINATION)

    def _plugin_config(self, plugin=None, config=None, **kwargs):
        return PluginConfig.objects.create(
            **{
                "team": self.team,
                "plugin": plugin or self._plugin(),
                "enabled": True,
                "order": 0,
                "config": config if config is not None else {"customerioSiteId": "site-1"},
                **kwargs,
            }
        )

    def test_creates_one_enabled_hog_function_carrying_the_config(self):
        plugin_config = self._plugin_config()

        result = self._migrate()

        assert result.created == [plugin_config.id]
        hog_function = self._hog_functions().get()
        assert hog_function.template_id == "plugin-customerio-plugin"
        assert hog_function.enabled is True
        assert hog_function.inputs["customerioSiteId"] == {"value": "site-1"}

    def test_dry_run_reports_without_writing(self):
        plugin_config = self._plugin_config()

        result = self._migrate(dry_run=True)

        assert result.created == [plugin_config.id]
        assert not self._hog_functions().exists()

    def test_rerunning_does_not_create_a_second_row_for_the_same_template(self):
        self._plugin_config()

        self._migrate()
        second = self._migrate()

        assert second.created == []
        assert list(second.skipped.values()) == ["already migrated"]
        assert self._hog_functions().count() == 1

    def test_leaves_the_plugin_config_enabled_so_rollback_is_deleting_the_hog_function(self):
        plugin_config = self._plugin_config()

        self._migrate()

        plugin_config.refresh_from_db()
        assert plugin_config.enabled is True

    def test_skips_plugins_without_a_bundled_template(self):
        plugin_config = self._plugin_config(plugin=self._plugin(url="https://github.com/PostHog/not-bundled"))

        result = self._migrate()

        assert result.created == []
        assert result.skipped == {plugin_config.id: "no bundled template for plugin-not-bundled"}

    def test_ignores_configs_that_the_legacy_consumer_never_runs(self):
        self._plugin_config(plugin=self._plugin(url="https://github.com/PostHog/geoip", methods=["processEvent"]))
        self._plugin_config(enabled=False)
        self._plugin_config(deleted=True)

        result = self._migrate()

        assert result.created == []
        assert not self._hog_functions().exists()

    def test_carries_the_plugin_config_id_only_for_storage_backed_plugins(self):
        HogFunctionTemplate.objects.create(
            template_id="plugin-first-time-event-tracker",
            sha="1",
            name="First time event tracker",
            code="",
            inputs_schema=[
                {"key": "events", "type": "string"},
                {"key": "legacy_plugin_config_id", "type": "string"},
            ],
            type="legacy_destination",
        )
        storage_backed = self._plugin_config(
            plugin=self._plugin(url="https://github.com/PostHog/first-time-event-tracker"),
            config={"events": "$pageview"},
        )
        self._plugin_config()

        self._migrate()

        tracker = self._hog_functions().get(template_id="plugin-first-time-event-tracker")
        assert tracker.inputs["legacy_plugin_config_id"] == {"value": str(storage_backed.id)}
        customerio = self._hog_functions().get(template_id="plugin-customerio-plugin")
        assert "legacy_plugin_config_id" not in customerio.inputs

    def test_refuses_a_config_whose_inputs_the_template_schema_does_not_cover(self):
        plugin_config = self._plugin_config(config={"customerioSiteId": "site-1", "removedOption": "x"})

        result = self._migrate(drop_unmapped_inputs=False)

        assert result.created == []
        assert result.skipped == {plugin_config.id: "inputs not in the template schema: removedOption"}
        assert not self._hog_functions().exists()

    def test_drops_unmapped_inputs_by_default_and_reports_what_went(self):
        plugin_config = self._plugin_config(config={"customerioSiteId": "site-1", "removedOption": "x"})

        result = self._migrate()

        assert result.created == [plugin_config.id]
        assert result.dropped_inputs == {plugin_config.id: ["removedOption"]}
        hog_function = self._hog_functions().get()
        assert hog_function.inputs["customerioSiteId"] == {"value": "site-1"}
        assert "removedOption" not in hog_function.inputs

    def test_moves_attachments_into_inputs(self):
        plugin_config = self._plugin_config()
        PluginAttachment.objects.create(
            team=self.team,
            plugin_config=plugin_config,
            key="mappings",
            content_type="application/json",
            file_name="mappings.json",
            file_size=2,
            contents=b'{"a": 1}',
        )

        self._migrate()

        hog_function = self._hog_functions().get(template_id="plugin-customerio-plugin")
        assert hog_function.inputs["mappings"] == {"value": {"a": 1}}

    def test_limits_to_the_requested_team(self):
        self._plugin_config()

        result = migrate_legacy_destinations(dry_run=False, team_ids=[self.team.id + 1])

        assert result.created == []


class TestDisableMigratedPluginConfigs(TestLegacyDestinationMigration):
    def _disable(self, dry_run=False):
        return disable_migrated_plugin_configs(dry_run=dry_run, team_ids=[self.team.id])

    def test_disables_only_a_config_a_migrated_hog_function_covers(self):
        covered = self._plugin_config()
        uncovered = self._plugin_config(plugin=self._plugin(url="https://github.com/PostHog/not-bundled"))

        self._migrate()
        disabled = self._disable()

        assert disabled == [covered.id]
        covered.refresh_from_db()
        uncovered.refresh_from_db()
        assert covered.enabled is False
        assert uncovered.enabled is True

    def test_leaves_everything_enabled_before_the_migration_runs(self):
        plugin_config = self._plugin_config()

        assert self._disable() == []
        plugin_config.refresh_from_db()
        assert plugin_config.enabled is True

    def test_dry_run_reports_without_disabling(self):
        plugin_config = self._plugin_config()
        self._migrate()

        assert self._disable(dry_run=True) == [plugin_config.id]
        plugin_config.refresh_from_db()
        assert plugin_config.enabled is True

    def test_ignores_a_migrated_row_that_is_disabled(self):
        plugin_config = self._plugin_config()
        self._migrate()
        self._hog_functions().update(enabled=False)

        assert self._disable() == []
        plugin_config.refresh_from_db()
        assert plugin_config.enabled is True
