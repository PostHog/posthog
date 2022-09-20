from posthog.async_migrations.definition import AsyncMigrationDefinition

"""
Migration Summary
- Context: https://github.com/PostHog/posthog/issues/5684
- Operations:
    0. Create a new table with the updated schema: `SAMPLE BY cityHash64(distinct_id)` + `ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`
    1. Start backfilling the new table (online) with data from partitions that are unlikely to be getting inserts (previous month and under)
    2. Detach the events_mv materialized view so we stop ingestion
    3. Insert the remaining events into the new table
    4. Rename the current table to `events_backup_0002_events_sample_by` and rename the new table to `events` (the table we use for querying)
    5. Attach the materialized view so we start ingestion again
    6. Optimize the table to remove duplicates
- Checks:
    0. is_required: only run this on instances with the old schema (new deploys get the new schema by default)
    1. precheck: make sure there's enough free disk space in CH to run the migration
    2. healthcheck: prevent CH from blowing up for lack of disk space
"""


class Migration(AsyncMigrationDefinition):

    description = (
        "Schema change to the events table ensuring our SAMPLE BY clause is compatible with ClickHouse >=21.7.0."
    )

    depends_on = "0001_events_sample_by"

    posthog_min_version = "1.33.0"
    posthog_max_version = "1.33.9"

    # Check older versions of the file for the migration code
