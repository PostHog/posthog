import dagster

from dags import (
    backups,
    ch_examples,
    deletes,
    export_query_logs_to_s3,
    materialized_columns,
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
        deletes.deletes_job,
        export_query_logs_to_s3.export_query_logs_to_s3,
        materialized_columns.materialize_column,
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
