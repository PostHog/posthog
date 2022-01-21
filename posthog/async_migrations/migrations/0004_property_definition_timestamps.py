import json
from functools import cached_property

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

    depends_on = "0003_fill_person_distinct_id2"

    @cached_property
    def operations(self):
        return [self.migrate_team_operation(team_id) for team_id in self._team_ids]

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
                created_at = first_event[0][0]
                last_seen_at = last_event[0][0]
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
                f"({prop}, {timestamps['created_at']}, {timestamps['last_seen_at']})"
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
                WHERE c.name = pd.name
            """,
            resumable=True,
            timeout_seconds=120,  # Fine tune and remove if not needed.
            rollback=f"""
                ALTER TABLE posthog_propertydefinition 
                DROP COLUMN IF EXISTS created_at,
                DROP COLUMN IF EXISTS last_seen_at
            """,
        )

    @cached_property
    def _team_ids(self):
        return list(EventDefinition.objects.order_by().values_list("team_id").distinct())
