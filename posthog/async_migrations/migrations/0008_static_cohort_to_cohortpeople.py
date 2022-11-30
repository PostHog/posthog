from functools import cached_property

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS

"""
Migration summary:

Currently, behavioral cohorts are backed by cohortpeople and static cohorts are backed by person_static_cohort. The cohortpeople table has been
significantly updated to support cohort versions and person versions/deletions. This migration will move person_static_cohort data to
cohortpeople so that cohort functionality is not supported by two tables that do almost the same thing.
"""


class Migration(AsyncMigrationDefinition):

    description = "Move person_static_cohort table to cohortpeople"

    depends_on = "0007_persons_and_groups_on_events_backfill"

    posthog_min_version = ""
    # After releasing this version we can remove code related to `person_static_cohort` table
    posthog_max_version = "1.42.99"

    # Only need to run if static cohort persons have been stored
    def is_required(self):
        rows_to_backfill_check = sync_execute(
            """
            SELECT 1
            FROM person_static_cohort
            WHERE LIMIT 1
            """
        )

        return len(rows_to_backfill_check) > 0

    @cached_property
    def operations(self):
        return [self.migrate_team_operation(team_id) for team_id in self._team_ids]

    def migrate_team_operation(self, team_id: int):
        return AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                INSERT INTO cohortpeople(person_id, cohort_id, team_id, sign, version)
                SELECT
                    person_id,
                    cohort_id,
                    team_id,
                    1 as sign,
                    0 as version
                FROM person_static_cohort
                WHERE team_id = {team_id}
            """,
            rollback=None,
        )

    @cached_property
    def _team_ids(self):
        return list(sorted(row[0] for row in sync_execute("SELECT DISTINCT team_id FROM person_static_cohort")))
