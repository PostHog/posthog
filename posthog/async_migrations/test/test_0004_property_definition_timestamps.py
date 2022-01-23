import json
from datetime import timedelta
from uuid import uuid4

import pytest
import pytz
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from freezegun.api import freeze_time

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import setup_async_migrations
from posthog.models import EventDefinition, Organization, PropertyDefinition, Team
from posthog.test.base import BaseTest

MIGRATION_NAME = "0004_property_definition_timestamps"


class Test0004PropertyDefinitionTimestamps(BaseTest):
    new_org: Organization = None  # type: ignore
    team2: Team = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.org = Organization.objects.create(name="New Organization")
        cls.team2 = Team.objects.create(name="New Project", organization=cls.org)

    def setUp(self):
        self.created_at_1 = timezone.now().astimezone(pytz.UTC)
        self.last_seen_at_1 = self.created_at_1 + timedelta(1)
        self.created_at_2 = timezone.now().astimezone(pytz.UTC) + timedelta(100)
        self.last_seen_at_2 = self.created_at_2 + timedelta(1)
        self.create_event_and_definitions(
            event="test_property_definition_timestamp_event", timestamp=self.created_at_1, team_id=self.team.id
        )
        self.create_event_and_definitions(
            event="test_property_definition_timestamp_event", timestamp=self.created_at_2, team_id=self.team2.id
        )

    @pytest.mark.ee
    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_migration(self):

        setup_async_migrations()
        migration_successful = start_async_migration(MIGRATION_NAME)
        self.assertTrue(migration_successful)

        # Check if migration is spoofed in `django_migrations`
        migration = MigrationRecorder.Migration.objects.filter(
            app="posthog", name="0199_property_definition_timestamps"
        )
        assert migration.exists() is True

        # Property without definition shouldn't get inserted
        property_nodef_1 = PropertyDefinition.objects.filter(name="prop_without_definition", team_id=self.team.id)
        property_nodef_2 = PropertyDefinition.objects.filter(name="prop_without_definition", team_id=self.team2.id)

        assert property_nodef_1.exists() is False
        assert property_nodef_2.exists() is False

        # Property with definition gets updated with correct created_at and last_seen_at
        property_def_1 = PropertyDefinition.objects.get(name="prop_with_definition", team_id=self.team.id)
        property_def_2 = PropertyDefinition.objects.get(name="prop_with_definition", team_id=self.team2.id)

        assert property_def_1.created_at == self.created_at_1
        assert property_def_1.last_seen_at == self.last_seen_at_1
        assert property_def_2.created_at == self.created_at_2
        assert property_def_2.last_seen_at == self.last_seen_at_2

    def create_event_and_definitions(self, event, timestamp, team_id):
        from ee.clickhouse.client import sync_execute

        properties = {"prop_with_definition": "def", "prop_without_definition": "nodef"}

        # Create two events and stagger timestamps
        sync_execute(
            """
            INSERT INTO events (uuid, event, properties, timestamp, team_id)
            VALUES (%(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s)
            """,
            {
                "uuid": uuid4(),
                "event": event,
                "properties": json.dumps(properties),
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "team_id": team_id,
            },
        )
        sync_execute(
            """
            INSERT INTO events (uuid, event, properties, timestamp, team_id)
            VALUES (%(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s)
            """,
            {
                "uuid": uuid4(),
                "event": event,
                "properties": json.dumps(properties),
                "timestamp": (timestamp + timedelta(1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "team_id": team_id,
            },
        )
        # And corresponding event definition
        EventDefinition.objects.create(name=event, team_id=team_id)

        # And corresponding property definitions
        PropertyDefinition.objects.create(name="prop_with_definition", team_id=team_id)

    def tearDown(self):
        from ee.clickhouse.client import sync_execute

        PropertyDefinition.objects.all().delete()
        EventDefinition.objects.all().delete()
        sync_execute("ALTER TABLE events DELETE WHERE event = 'test_property_definition_timestamp_event'")
