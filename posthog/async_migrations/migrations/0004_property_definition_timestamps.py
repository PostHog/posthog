import json
from functools import cached_property

import pytz
from dateutil.parser import isoparse

from ee.clickhouse.client import sync_execute
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.constants import AnalyticsDBMS
from posthog.models import EventDefinition

"""
Migration summary:

Adds created_at and last_seen_at properties for property definitions.

Migration strategy:

    1. select all event definitions
    2. find first occurring event for each event definition
    3. loop through events' properties and keep map of property definitions to earliest and latest seen times in memory
    4. update all property definitions with created_at

We populate event property definitions team by team to avoid running out of memory.

"""


class Migration(AsyncMigrationDefinition):
    description = "Determine created_at and last_seen_at properties for event property definitions."

    posthog_min_version = "1.30.0"

    depends_on = "0003_fill_person_distinct_id2"

    depends_on_posthog_migration = "0199_property_definition_timestamps"

    @cached_property
    def operations(self):
        return [self.setup_columns()] + [self.migrate_team_operation(team_id) for team_id in self._team_ids]

    def setup_columns(self):
        """
        Manually runs the sql that Django auto-generates (via `sqlmigrate` command) for
        `posthog/migrations/0199_property_definition_timestamps`. Creates new columns and also tricks Django into
        thinking that the migration is already run by adding the corresponding row into the `django_migrations` table.

        This is necessary in order to avoid having an in-between state where `created_at` and `last_seen_at` columns
        exist but don't mean anything. The actual 0199 migration has been edited to run the `sqlmigrate` generated
        comment with an extra `IF [NOT] EXISTS` clause so that Django doesn't error out if it chooses to add the column
        after this migration already creates it, essentially making it a noop. This means that 0199 can be run before,
        during, or after the async migration without consequence, which overcomes the timing problem.
        """

        return AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.POSTGRES,
            resumable=True,
            sql=f"""
                        COMMIT;
                        BEGIN;
                        ALTER TABLE "posthog_propertydefinition" 
                        ADD COLUMN IF NOT EXISTS "created_at" timestamp with time zone NULL,
                        ADD COLUMN IF NOT EXISTS "last_seen_at" timestamp with time zone NULL;
                        
                        INSERT INTO "django_migrations" (app, name, applied)
                        VALUES ('posthog', '{self.depends_on_posthog_migration}', NOW())
                        ON CONFLICT DO NOTHING
                    """,
            rollback=f"""
                        COMMIT;
                        BEGIN;
                        ALTER TABLE "posthog_propertydefinition" 
                        DROP COLUMN IF EXISTS "created_at",
                        DROP COLUMN IF EXISTS "last_seen_at";
                        
                        DELETE FROM "django_migrations"
                        WHERE app = 'posthog' AND name = '${self.depends_on_posthog_migration}'
                    """,
        )

    def migrate_team_operation(self, team_id: int):

        property_defs = {}
        for instance in EventDefinition.objects.filter(team_id=team_id):
            first_event = sync_execute(
                """
                SELECT timestamp, properties FROM events WHERE team_id=%(team_id)s AND event=%(event)s
                ORDER BY timestamp LIMIT 1
                """,
                {"team_id": instance.team.pk, "event": instance.name,},
            )
            last_event = sync_execute(
                """
                SELECT timestamp, properties FROM events WHERE team_id=%(team_id)s AND event=%(event)s
                ORDER BY timestamp DESC LIMIT 1
                """,
                {"team_id": instance.team.pk, "event": instance.name,},
            )

            if first_event:
                # clickhouse specific formatting
                created_at = first_event[0][0]
                created_at = isoparse(created_at) if isinstance(created_at, str) else created_at.astimezone(pytz.utc)
                last_seen_at = last_event[0][0]
                last_seen_at = (
                    isoparse(last_seen_at) if isinstance(last_seen_at, str) else last_seen_at.astimezone(pytz.utc)
                )
                property_keys = list(json.loads(first_event[0][1]).keys())

                for prop in property_keys:
                    if prop not in property_defs:
                        property_defs[prop] = dict(created_at=created_at, last_seen_at=last_seen_at)
                    else:
                        if created_at < property_defs[prop]["created_at"]:
                            property_defs[prop]["created_at"] = created_at
                        if last_seen_at > property_defs[prop]["last_seen_at"]:
                            property_defs[prop]["last_seen_at"] = last_seen_at

        property_defs_sql = ",".join(
            [
                f"""
                (
                    '{prop}', 
                    to_timestamp('{timestamps['created_at'].strftime('%Y-%m-%d %H:%M:%S.%f')}', 'YYYY-MM-DD HH24:MI:SS.USZ'), 
                    to_timestamp('{timestamps['last_seen_at'].strftime('%Y-%m-%d %H:%M:%S.%f')}', 'YYYY-MM-DD HH24:MI:SS.USZ')
                )
                """
                for [prop, timestamps] in property_defs.items()
            ]
        )

        return AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.POSTGRES,
            sql=f"""
                UPDATE posthog_propertydefinition as pd SET
                    created_at = c.created_at,
                    last_seen_at = c.last_seen_at
                FROM (VALUES
                    {property_defs_sql}
                ) AS c(name, created_at, last_seen_at)
                WHERE c.name = pd.name AND pd.team_id = {team_id}
            """,
            resumable=True,
            timeout_seconds=120,
            rollback=f"""
                UPDATE posthog_propertydefinition 
                SET created_at = NULL, last_seen_at = NULL
                WHERE team_id = {team_id}
            """,
        )

    @cached_property
    def _team_ids(self):
        return list(EventDefinition.objects.order_by().values_list("team_id", flat=True).distinct())
