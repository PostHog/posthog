from typing import Optional

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from posthog.test.base import BaseTest

"""
If you're looking at this, you can probably remove this
"""


class TestMigrations(BaseTest):
    @property
    def app(self) -> str:
        app_config = apps.get_containing_app_config(type(self).__module__)
        assert app_config is not None
        return app_config.name

    @property
    def migrate_from(self) -> Optional[str]:
        raise NotImplementedError(f"TestCase '{type(self).__name__}' must define migrate_from property")

    @property
    def migrate_to(self) -> Optional[str]:
        raise NotImplementedError(f"TestCase '{type(self).__name__}' must define migrate_to property")

    def setUpBeforeMigration(self, apps):
        pass

    def setUp(self):
        migrate_from = [(self.app, self.migrate_from)]
        migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps  # type: ignore

        # Reverse to the original migration
        executor.migrate(migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.
        executor.migrate(migrate_to)

        self.apps = executor.loader.project_state(migrate_to).apps  # type: ignore


class Test(TestMigrations):

    migrate_from = "0203_dashboard_permissions"
    migrate_to = "0204_remove_duplicate_plugin_configs"

    def setUpBeforeMigration(self, apps):
        PluginConfig = apps.get_model("posthog", "PluginConfig")
        Plugin = apps.get_model("posthog", "Plugin")
        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")
        plugin = Plugin.objects.create(organization=Organization.objects.get())
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin, order=0)
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin, order=1)

        plugin2 = Plugin.objects.create(organization=Organization.objects.get())
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin2, order=0)
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin2, order=1)
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin2, order=2)

        plugin3 = Plugin.objects.create(organization=Organization.objects.get())
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin3, order=0, enabled=False)
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin3, order=1, enabled=True)
        PluginConfig.objects.create(team=Team.objects.get(), plugin=plugin3, order=2, enabled=False)

    def test_yes(self):
        PluginConfig = apps.get_model("posthog", "PluginConfig")
        configs = PluginConfig.objects.all()
        self.assertEqual(len(configs), 3)
        self.assertEqual(configs[0].order, 0)
        self.assertEqual(configs[1].order, 0)
        self.assertEqual(configs[2].order, 1)
