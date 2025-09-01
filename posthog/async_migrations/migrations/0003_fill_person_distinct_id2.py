from functools import cached_property

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.clickhouse.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.settings import CLICKHOUSE_DATABASE

"""
Migration summary:

Schema change to migrate the data from the old person_distinct_id table
to the new person_distinct_id2 table.

The reason this is needed is for faster `person_distinct_id` queries as the
old schema worked off of (distinct_id, person_id) pairs, making it expensive
to for our analytics queries, which need to map from distinct_id -> latest person_id.

The new schema works off of distinct_id columns, leveraging ReplacingMergeTrees
with a version column we store in postgres.

We migrate teams one-by-one to avoid running out of memory.

The migration strategy:

    1. write to both pdi and pdi2 any new updates (done prior to this migration)
    2. insert all non-deleted (team_id, distinct_id, person_id) rows from pdi into pdi2 (this migration)
    3. Once migration has run, we only read/write from/to pdi2.
"""


class Migration(AsyncMigrationDefinition):
    description = "Set up person_distinct_id2 table, speeding up person-related queries."

    depends_on = "0002_events_sample_by"

    posthog_min_version = "1.33.0"
    # After releasing this version we can remove code related to `person_distinct_id` table
    posthog_max_version = "1.33.9"

    def is_required(self):
        rows = sync_execute(
            """
            SELECT comment
            FROM system.columns
            WHERE database = %(database)s
        """,
            {"database": CLICKHOUSE_DATABASE},
        )

        comments = [row[0] for row in rows]
        return "skip_0003_fill_person_distinct_id2" not in comments

    @cached_property
    def operations(self):
        return [self.migrate_team_operation(team_id) for team_id in self._team_ids]

    def migrate_team_operation(self, team_id: int):
        return AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                INSERT INTO person_distinct_id2(team_id, distinct_id, person_id, is_deleted, version)
                SELECT
                    team_id,
                    distinct_id,
                    argMax(person_id, _timestamp) as person_id,
                    0 as is_deleted,
                    0 as version
                FROM (
                    SELECT
                        distinct_id,
                        person_id,
                        any(team_id) as team_id,
                        max(_timestamp) as _timestamp
                    FROM
                        person_distinct_id
                    WHERE
                        person_distinct_id.team_id = {team_id}
                    GROUP BY
                        person_id,
                        distinct_id
                    HAVING
                        max(is_deleted) = 0
                )
                GROUP BY team_id, distinct_id
            """,
            rollback=None,
        )

    @cached_property
    def _team_ids(self):
        return sorted(row[0] for row in sync_execute("SELECT DISTINCT team_id FROM person_distinct_id"))
