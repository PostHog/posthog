
from django.apps import apps
from django.test import TestCase
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from typing import Optional


class TestMigrations(TestCase):

    @property
    def app(self):
        return apps.get_containing_app_config(type(self).__module__).name

    migrate_from: Optional[str] = None
    migrate_to: Optional[str] = None

    def setUp(self):
        assert self.migrate_from and self.migrate_to, \
            "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)
        self.migrate_from = [(self.app, self.migrate_from)]
        self.migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        # Reverse to the original migration
        executor.migrate(self.migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.
        with self.assertNumQueries(108):
            executor.migrate(self.migrate_to)

        self.apps = executor.loader.project_state(self.migrate_to).apps

    def setUpBeforeMigration(self, apps):
        pass


class TagsTestCase(TestMigrations):

    migrate_from = '0038_migrate_actions_to_precalculate_events'
    migrate_to = '0039_populate_event_ip_property'

    def setUpBeforeMigration(self, apps):
        max_event_count = 1000000
        default_event_count = 100
        Event = apps.get_model('posthog', 'Event')
        Team = apps.get_model('posthog', 'Team')
        team = Team.objects.create()

        for i in range(default_event_count):
            event = Event.objects.create(team=team, event='$autocapture', ip="127.0.0.1")

        null_ip_event = Event.objects.create(team=team, event='$null_ip')

    def test_ip_migrated(self):
        Event = apps.get_model('posthog', 'Event')

        events = Event.objects.all() 
        for e in events:
            if e.event == '$autocapture':     
                self.assertEqual(e.properties.get("$ip"), "127.0.0.1")
                self.assertEqual(e.properties.get("$ip"), "127.0.0.1")
            if e.event == '$null_ip':
                self.assertEqual(e.properties.get("$ip"), None)
