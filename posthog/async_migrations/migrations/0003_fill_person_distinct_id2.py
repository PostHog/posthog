from constance import config
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import EVENTS_TABLE
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.constants import AnalyticsDBMS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.version_requirement import ServiceVersionRequirement


class Migration(AsyncMigrationDefinition):

    description = """
        Schema change to migrate the data from the old person_distinct_id table
        to the new person_distinct_id2 table. This is required as the existing
        person_distinct_id does not use a strictly increasing id for
        identifying the latest (distinct_id, person_id) pairing. If we assume
        that a delete is always the latest then we can assume that any delete is
        enough to distinguish if a pairing is deleted or not.

        Aside from correctness, which we can handle as we're assuming that
        persons can't be undeleted, the current setup results in very slow query
        performance for large teams. e.g. [this
        query](https://github.com/PostHog/posthog/blob/bcf2b6370f8d2205f1f7d5fb5f431124c3848691/ee/clickhouse/sql/person.py#L255:L255)
        is slow.

        The issue is highlighted by the fact that we can have the scenario:

            1. "person 1" is associated with "distinct_id A"
            2. "person 1" is deleted resulting in a new row being written with is_deleted = 1

        The data can end up looking like:

        _timestamp            |  distinct_id |  person_id  |  is_deleted
        ----------------------+--------------+-------------+--------------
        2019-01-01 10:10:10   |  A           |  1          |  0
        2019-01-01 10:10:10   |  A           |  1          |  1

        Hence there is no way of telling if the person was first deleted then
        re-associated or the other way around. Hence at the moment with the old
        table we're just checking that all rows relating to a (distinct_id,
        person_id) pair are marked as is_deleted = 0.

        The person_distinct_id table uses the `CollapsingMergeTree` engine, which
        will at some point pair these two rows together, but we can't rely on
        waiting. It also means that if we've have to be diligent with ensuring
        we have written cancel rows correctly. It's good for cases where we
        might want to perform aggregation over data, but `ReplacingMergeTree` is
        a better fix where we just want the latest data.

        The new schema includes a `version` column which is strictly
        increasing. At the time of writing, this version is a big int
        [updated in a
        transaction](https://github.com/PostHog/posthog/blob/bcf2b6370f8d2205f1f7d5fb5f431124c3848691/plugin-server/src/worker/ingestion/properties-updater.ts#L58:L58)
        within postgres, then propagated to clickhouse on successful commit via
        kafka.

        NOTE: if there have been previous runs of this migrate we should be
        safe, adding additional rows should not be an issue as we're adding
        these with version = 0.

        The migration strategy:

         1. write to both pdi and pdi2 any new updates (already done separate to
            this migration)
         2. insert all non-deleted (team_id, distinct_id, person_id) rows from pdi
            into pdi2 (this migration)
         3. update app to always use pdi2
    """

    # After releasing this version we can remove code related to `person_distinct_id` table
    posthog_max_version = "1.34.0"

    operations = [
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                INSERT INTO person_distinct_id2(
                        team_id,
                        distinct_id,
                        person_id,
                        is_deleted,
                        version
                    )
                    /*
                    Get all team_id, distinct_id, person_id tuples that
                    haven't been deleted.

                    Note that this query differs from the exact existing
                    person_distinct_id query currently in the codebase, e.g.
                    [this one](https://github.com/PostHog/posthog/blob/bcf2b6370f8d2205f1f7d5fb5f431124c3848691/ee/clickhouse/sql/person.py#L255:L255)
                    in that it isn't filtering by team_id. We might need to
                    reconsider that to avoid out of memory issues.

                    SELECT * FROM <old_query>
                    FULL JOIN <new_query> new ON old.distinct_id = new.distinct_id
                    WHERE old.person_id <> new.person_id

                    NOTE: where the query differs, I have left the original query
                    part commented out.
                    */
                SELECT -- any(team_id) as team_id,
                    team_id,
                    distinct_id,
                    argMax(person_id, _timestamp) as person_id,
                    0 as is_deleted,
                    0 as version
                FROM (
                        SELECT distinct_id,
                            person_id,
                            team_id,
                            max(_timestamp) as _timestamp
                        FROM person_distinct_id -- WHERE team_id = 2
                        GROUP BY team_id,
                            person_id,
                            distinct_id
                        HAVING max(is_deleted) = 0
                    ) -- GROUP BY distinct_id
                GROUP BY team_id,
                    distinct_id
            """,
            resumable=True,
        ),
    ]

    def is_required(self):
        rows = sync_execute(
            """
            SELECT comment
            FROM system.columns
            WHERE database = %(database)s AND table = 'person_distinct_id' AND name = 'distinct_id'
        """,
            {"database": CLICKHOUSE_DATABASE},
        )

        return len(rows) > 0 and rows[0][0] != "skip_0003_fill_person_distinct_id2"

    def precheck(self):
        raise NotImplementedError("todo")

    def healthcheck(self):
        raise NotImplementedError("todo")
