
from django.apps import apps
from django.test import TestCase
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from typing import Optional


class TestMigrations(TestCase):

    @property
    def app(self) -> str:
        app_config = apps.get_containing_app_config(type(self).__module__)
        assert app_config is not None
        return app_config.name

    @property
    def migrate_from(self) -> Optional[str]:
        raise NotImplementedError("TestCase '{}' must define migrate_from property".format(type(self).__name__))

    @property
    def migrate_to(self) -> Optional[str]:
        raise NotImplementedError("TestCase '{}' must define migrate_to property".format(type(self).__name__))

    def setUpBeforeMigration(self, apps):
        pass

    def setUp(self):
        migrate_from = [(self.app, self.migrate_from)]
        migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps # type: ignore

        # Reverse to the original migration
        executor.migrate(migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.
        with self.assertNumQueries(8):
            executor.migrate(migrate_to)

        self.apps = executor.loader.project_state(migrate_to).apps  # type: ignore


class EventPartitionsTestCase(TestMigrations):

    migrate_from = '0049_delete_funnelstep'
    migrate_to = '0050_event_partitions'

    def setUpBeforeMigration(self, apps):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM information_schema.tables WHERE table_name = \'posthog_event_default\'')
            exists = cursor.fetchone()
        self.assertIsNone(exists)

    def test_partition_exists_migrated(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM information_schema.tables WHERE table_name = \'posthog_event_default\'')
            exists = cursor.fetchone()
        self.assertIsNotNone(exists)

