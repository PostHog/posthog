from functools import cached_property

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.models.cohort import Cohort

"""
Migration summary:
Currently, behavioral cohorts are backed by cohortpeople and static cohorts are backed by person_static_cohort. The cohortpeople table has been
significantly updated to support cohort versions and person versions/deletions. This migration will move person_static_cohort data and cohortpeople
to a new table cohort_actors
"""


class Migration(AsyncMigrationDefinition):

    description = "Move person_static_cohort and cohortpeople table to cohort_actors"

    depends_on = "0007_persons_and_groups_on_events_backfill"

    # After releasing this version we can remove code related to `person_static_cohort` table
    posthog_max_version = "1.42.99"

    # Only need to run if static cohort persons have been stored
    def is_required(self):
        static_rows_to_backfill_check = sync_execute(
            """
            SELECT 1
            FROM person_static_cohort
            LIMIT 1
            """
        )

        rows_to_backfill_check = sync_execute(
            """
            SELECT 1
            FROM cohortpeople
            LIMIT 1
            """
        )

        return len(static_rows_to_backfill_check) > 0 or len(rows_to_backfill_check) > 0

    @cached_property
    def operations(self):
        return [self.migrate_cohort(cohort) for cohort in self._cohorts]

    @cached_property
    def _cohorts(self):
        return [cohort for cohort in Cohort.objects.all()]

    def migrate_cohort(self, cohort: Cohort):
        if cohort.is_static:
            return self._migrate_static_cohort_operation(cohort)
        else:
            return self._migrate_cohort_operation(cohort)

    def _migrate_static_cohort_operation(self, cohort: Cohort):
        return AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                INSERT INTO cohort_actors(actor_id, cohort_id, team_id, version)
                SELECT
                    toString(person_id),
                    cohort_id,
                    team_id,
                    0 as version
                FROM person_static_cohort
                WHERE team_id = {cohort.team.pk} AND cohort_id = {cohort.pk}
            """,
            rollback=None,
        )

    def _migrate_cohort_operation(self, cohort: Cohort):
        return AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                INSERT INTO cohort_actors(actor_id, cohort_id, team_id, version)
                SELECT
                    toString(person_id),
                    cohort_id,
                    team_id,
                    version
                FROM cohortpeople
                WHERE team_id = {cohort.team.pk} AND cohort_id = {cohort.pk} AND version = {cohort.version}
            """,
            rollback=None,
        )
