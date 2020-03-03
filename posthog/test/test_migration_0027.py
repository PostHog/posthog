
from django.apps import apps
from django.test import TestCase
from django.db.migrations.executor import MigrationExecutor
from django.db import connection


class TestMigrations(TestCase):

    @property
    def app(self):
        return apps.get_containing_app_config(type(self).__module__).name

    migrate_from = None
    migrate_to = None

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
        with self.assertNumQueries(22):
            executor.migrate(self.migrate_to)

        self.apps = executor.loader.project_state(self.migrate_to).apps

    def setUpBeforeMigration(self, apps):
        pass


class TagsTestCase(TestMigrations):

    migrate_from = '0026_auto_20200227_0804'
    migrate_to = '0027_move_elements_to_group'

    def setUpBeforeMigration(self, apps):
        Event = apps.get_model('posthog', 'Event')
        Element = apps.get_model('posthog', 'Element')
        Team = apps.get_model('posthog', 'Team')
        team = Team.objects.create()
        event = Event.objects.create(team=team, event='$autocapture')
        Element.objects.create(event=event, order=0, tag_name='button')
        Element.objects.create(event=event, order=1, tag_name='div')

        event = Event.objects.create(team=team, event='$autocapture')
        Element.objects.create(event=event, order=0, tag_name='button')
        Element.objects.create(event=event, order=1, tag_name='div')

    def test_tags_migrated(self):
        Event = apps.get_model('posthog', 'Event')
        Element = apps.get_model('posthog', 'Element')
        ElementGroup = apps.get_model('posthog', 'ElementGroup')

        group = ElementGroup.objects.get()
        events = Event.objects.all()
        self.assertEqual(events[0].elements_hash, group.hash)
        self.assertEqual(events[1].elements_hash, group.hash)
        elements = Element.objects.all()
        self.assertEqual(elements[0].event, None)
        self.assertEqual(elements[0].group, group)
        self.assertEqual(len(elements), 2)