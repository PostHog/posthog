from posthog.async_migrations.definition import AsyncMigrationDefinition

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
    posthog_max_version = "1.33.9"

    # Check older versions of the file for the migration code
