
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


class TagsTestCase(TestMigrations):

    migrate_from = '0038_migrate_actions_to_precalculate_events'
    migrate_to = '0039_populate_event_ip_property'

    def setUpBeforeMigration(self, apps):
        max_event_count = 1000000
        max_batch_size = 10000
        default_event_count = 100
        default_batch_size = 10
        Event = apps.get_model('posthog', 'Event')
        Team = apps.get_model('posthog', 'Team')
        team = Team.objects.create()

        Event.objects.bulk_create([
            Event(team=team, event='$autocapture', ip="127.0.0.1")
                for i in range(default_event_count)], default_batch_size)

        Event.objects.bulk_create([
            Event(team=team, event='$prefilled_properties', distinct_id="2",
            ip="192.2.2.1", properties={"$os": "MacOS"})
                for i in range(default_event_count)], default_batch_size)

        null_ip_event = Event.objects.create(team=team, event='$null_ip')

    def test_ip_migrated(self):
        Event = apps.get_model('posthog', 'Event')

        events = Event.objects.all()
        for e in events:
            if e.event == '$prefilled_properties':
                self.assertEqual(e.properties.get("$ip"), "192.2.2.1")
                self.assertEqual(e.properties.get("$ip"), "192.2.2.1")
                self.assertEqual(e.properties.get("$os"), "MacOS")

            if e.event == '$autocapture':
                self.assertEqual(e.properties.get("$ip"), "127.0.0.1")
                self.assertEqual(e.properties.get("$ip"), "127.0.0.1")
            if e.event == '$null_ip':
                self.assertEqual(e.properties.get("$ip"), None)
