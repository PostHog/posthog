import dagster

from posthog.dags import (
    add_index_to_materialized_column,
    backfill_materialized_column,
    backups,
    ch_examples,
    create_materialized_column,
    deletes,
    export_query_logs_to_s3,
    fix_person_id_overrides,
    orm_examples,
    person_overrides,
    postgres_to_clickhouse_etl,
    property_definitions,
)

from . import resources

defs = dagster.Definitions(
    assets=[
        ch_examples.get_clickhouse_version,
        ch_examples.print_clickhouse_version,
        orm_examples.process_pending_deletions,
        orm_examples.pending_deletions,
        postgres_to_clickhouse_etl.organizations_in_clickhouse,
        postgres_to_clickhouse_etl.teams_in_clickhouse,
    ],
    jobs=[
        add_index_to_materialized_column.add_index_to_materialized_column,
        create_materialized_column.create_materialized_column,
        deletes.deletes_job,
        export_query_logs_to_s3.export_query_logs_to_s3,
        backfill_materialized_column.backfill_materialized_column,
        fix_person_id_overrides.fix_person_id_overrides_job,
        person_overrides.cleanup_orphaned_person_overrides_snapshot,
        person_overrides.squash_person_overrides,
        postgres_to_clickhouse_etl.postgres_to_clickhouse_etl_job,
        property_definitions.property_definitions_ingestion_job,
        backups.sharded_backup,
        backups.non_sharded_backup,
    ],
    schedules=[
        export_query_logs_to_s3.query_logs_export_schedule,
        person_overrides.squash_schedule,
        postgres_to_clickhouse_etl.postgres_to_clickhouse_hourly_schedule,
        property_definitions.property_definitions_hourly_schedule,
        backups.full_sharded_backup_schedule,
        backups.incremental_sharded_backup_schedule,
        backups.full_non_sharded_backup_schedule,
        backups.incremental_non_sharded_backup_schedule,
    ],
    sensors=[
        deletes.run_deletes_after_squash,
    ],
    resources=resources,
)
