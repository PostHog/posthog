import json
from datetime import timedelta
from uuid import uuid4

import pytest
import pytz
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from freezegun.api import freeze_time

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.models import EventDefinition, PropertyDefinition, Team, User
from posthog.test.base import BaseTest

MIGRATION_NAME = "0004_property_definition_timestamps"


@pytest.mark.ee
class Test0004PropertyDefinitionTimestamps(BaseTest):
    def setUp(self):
        self.migration = get_async_migration_definition(MIGRATION_NAME)
        self.timestamp = 0

        # Make sure migration 0199_property_definition_timestamps has already been run
        with connection.cursor() as cursor:
            cursor.execute(
                """
                        COMMIT;
                        BEGIN;
                        ALTER TABLE "posthog_propertydefinition"
                        ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NULL,
                        ADD COLUMN IF NOT EXISTS "last_seen_at" timestamp with time zone NULL;

                        INSERT INTO "django_migrations" (app, name, applied)
                        VALUES ('posthog', '0199_property_definition_timestamps', NOW())
                        ON CONFLICT DO NOTHING
                    """
            )

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_migration(self):
        # Setup
        created_at_1 = timezone.now().astimezone(pytz.UTC)
        last_seen_at_1 = created_at_1 + timedelta(1)
        created_at_2 = timezone.now().astimezone(pytz.UTC) + timedelta(100)
        last_seen_at_2 = created_at_2 + timedelta(1)
        self.create_event_and_definitions(
            event="test_property_definition_timestamp_event", timestamp=created_at_1, team_id=1
        )
        self.create_event_and_definitions(
            event="test_property_definition_timestamp_event", timestamp=created_at_2, team_id=2
        )

        setup_async_migrations()
        migration_successful = start_async_migration(MIGRATION_NAME)
        self.assertTrue(migration_successful)

        # Check if migration is spoofed in `django_migrations`
        migration = MigrationRecorder.Migration.objects.filter(
            app="posthog", name="0199_property_definition_timestamps"
        )
        assert migration.exists() is True

        # Property without definition shouldn't get inserted
        property_nodef_1 = PropertyDefinition.objects.filter(name="prop_without_definition", team_id=1)
        property_nodef_2 = PropertyDefinition.objects.filter(name="prop_without_definition", team_id=2)

        assert property_nodef_1.exists() is False
        assert property_nodef_2.exists() is False

        # Property with definition gets updated with correct created_at and last_seen_at
        property_def_1 = PropertyDefinition.objects.get(name="prop_with_definition", team_id=1)
        property_def_2 = PropertyDefinition.objects.get(name="prop_with_definition", team_id=2)

        assert property_def_1.created_at == created_at_1
        assert property_def_1.last_seen_at == last_seen_at_1
        assert property_def_2.created_at == created_at_2
        assert property_def_2.last_seen_at == last_seen_at_2

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

        with connection.cursor() as cursor:
            cursor.execute(
                """
                        COMMIT;
                        BEGIN;
                        ALTER TABLE "posthog_propertydefinition" 
                        DROP COLUMN IF EXISTS "created_at",
                        DROP COLUMN IF EXISTS "last_seen_at";
                        
                        DELETE FROM "django_migrations"
                        WHERE app = 'posthog' AND name = '0199_property_definition_timestamps'
                    """
            )
