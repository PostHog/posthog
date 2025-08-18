from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_NEW_TABLE_SQL,
    QUERY_LOG_ARCHIVE_NEW_MV,
)

operations = [
    # Step 1: Create new table with team_id in ordering key
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
    # Step 2: Create new materialized view to populate the new table
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 3: Get the earliest event_time in the new table (if any)
    # and insert historical data from old table
    run_sql_with_exceptions(
        """
        INSERT INTO query_log_archive_new
        SELECT
            hostname,
            user,
            query_id,
            type,
            event_date,
            event_time,
            event_time_microseconds,
            query_start_time,
            query_start_time_microseconds,
            query_duration_ms,
            read_rows,
            read_bytes,
            written_rows,
            written_bytes,
            result_rows,
            result_bytes,
            memory_usage,
            peak_threads_usage,
            current_database,
            query,
            formatted_query,
            normalized_query_hash,
            query_kind,
            exception_code,
            exception,
            stack_trace,
            ProfileEvents_RealTimeMicroseconds,
            ProfileEvents_OSCPUVirtualTimeMicroseconds,
            ProfileEvents_S3Clients,
            ProfileEvents_S3DeleteObjects,
            ProfileEvents_S3CopyObject,
            ProfileEvents_S3ListObjects,
            ProfileEvents_S3HeadObject,
            ProfileEvents_S3GetObjectAttributes,
            ProfileEvents_S3CreateMultipartUpload,
            ProfileEvents_S3UploadPartCopy,
            ProfileEvents_S3UploadPart,
            ProfileEvents_S3AbortMultipartUpload,
            ProfileEvents_S3CompleteMultipartUpload,
            ProfileEvents_S3PutObject,
            ProfileEvents_S3GetObject,
            ProfileEvents_ReadBufferFromS3Bytes,
            ProfileEvents_WriteBufferFromS3Bytes,
            lc_workflow,
            lc_kind,
            lc_id,
            lc_route_id,
            lc_access_method,
            lc_query_type,
            lc_product,
            lc_chargeable,
            lc_name,
            lc_client_query_id,
            lc_org_id,
            lc_team_id as team_id,  -- Map lc_team_id to team_id
            lc_user_id,
            lc_session_id,
            lc_dashboard_id,
            lc_insight_id,
            lc_cohort_id,
            lc_batch_export_id,
            lc_experiment_id,
            lc_experiment_feature_flag_key,
            '' as lc_alert_config_id,  -- Field doesn't exist in old table
            '' as lc_feature,  -- Field doesn't exist in old table
            '' as lc_table_id,  -- Field doesn't exist in old table
            0 as lc_warehouse_query,  -- Field doesn't exist in old table
            '' as lc_person_on_events_mode,  -- Field doesn't exist in old table
            '' as lc_service_name,  -- Field doesn't exist in old table
            '' as lc_workload,  -- Field doesn't exist in old table
            lc_query__kind,
            lc_query__query,
            lc_temporal__workflow_namespace,
            lc_temporal__workflow_type,
            lc_temporal__workflow_id,
            lc_temporal__workflow_run_id,
            lc_temporal__activity_type,
            lc_temporal__activity_id,
            lc_temporal__attempt,
            lc_dagster__job_name,
            lc_dagster__run_id,
            lc_dagster__owner
        FROM query_log_archive
        WHERE event_time < (
            SELECT min(event_time) - INTERVAL 10 MINUTE
            FROM query_log_archive_new
            WHERE event_time > toDateTime('2000-01-01 00:00:00')
        )
        """,
        node_role=NodeRole.ALL,
    ),
    # Step 4: Handle transition period with deduplication
    # Insert records from the transition period that don't exist in the new table
    run_sql_with_exceptions(
        """
        INSERT INTO query_log_archive_new
        SELECT
            hostname,
            user,
            query_id,
            type,
            event_date,
            event_time,
            event_time_microseconds,
            query_start_time,
            query_start_time_microseconds,
            query_duration_ms,
            read_rows,
            read_bytes,
            written_rows,
            written_bytes,
            result_rows,
            result_bytes,
            memory_usage,
            peak_threads_usage,
            current_database,
            query,
            formatted_query,
            normalized_query_hash,
            query_kind,
            exception_code,
            exception,
            stack_trace,
            ProfileEvents_RealTimeMicroseconds,
            ProfileEvents_OSCPUVirtualTimeMicroseconds,
            ProfileEvents_S3Clients,
            ProfileEvents_S3DeleteObjects,
            ProfileEvents_S3CopyObject,
            ProfileEvents_S3ListObjects,
            ProfileEvents_S3HeadObject,
            ProfileEvents_S3GetObjectAttributes,
            ProfileEvents_S3CreateMultipartUpload,
            ProfileEvents_S3UploadPartCopy,
            ProfileEvents_S3UploadPart,
            ProfileEvents_S3AbortMultipartUpload,
            ProfileEvents_S3CompleteMultipartUpload,
            ProfileEvents_S3PutObject,
            ProfileEvents_S3GetObject,
            ProfileEvents_ReadBufferFromS3Bytes,
            ProfileEvents_WriteBufferFromS3Bytes,
            lc_workflow,
            lc_kind,
            lc_id,
            lc_route_id,
            lc_access_method,
            lc_query_type,
            lc_product,
            lc_chargeable,
            lc_name,
            lc_client_query_id,
            lc_org_id,
            lc_team_id as team_id,
            lc_user_id,
            lc_session_id,
            lc_dashboard_id,
            lc_insight_id,
            lc_cohort_id,
            lc_batch_export_id,
            lc_experiment_id,
            lc_experiment_feature_flag_key,
            '' as lc_alert_config_id,  -- Field doesn't exist in old table
            '' as lc_feature,  -- Field doesn't exist in old table
            '' as lc_table_id,  -- Field doesn't exist in old table
            0 as lc_warehouse_query,  -- Field doesn't exist in old table
            '' as lc_person_on_events_mode,  -- Field doesn't exist in old table
            '' as lc_service_name,  -- Field doesn't exist in old table
            '' as lc_workload,  -- Field doesn't exist in old table
            lc_query__kind,
            lc_query__query,
            lc_temporal__workflow_namespace,
            lc_temporal__workflow_type,
            lc_temporal__workflow_id,
            lc_temporal__workflow_run_id,
            lc_temporal__activity_type,
            lc_temporal__activity_id,
            lc_temporal__attempt,
            lc_dagster__job_name,
            lc_dagster__run_id,
            lc_dagster__owner
        FROM query_log_archive AS old
        WHERE event_time >= (
            SELECT min(event_time) - INTERVAL 10 MINUTE
            FROM query_log_archive_new
            WHERE event_time > toDateTime('2000-01-01 00:00:00')
        )
        AND event_time <= (
            SELECT min(event_time) + INTERVAL 10 MINUTE
            FROM query_log_archive_new
            WHERE event_time > toDateTime('2000-01-01 00:00:00')
        )
        AND NOT EXISTS (
            SELECT 1
            FROM query_log_archive_new AS new
            WHERE new.query_id = old.query_id
            AND new.event_time >= old.event_time - INTERVAL 1 MINUTE
            AND new.event_time <= old.event_time + INTERVAL 1 MINUTE
        )
        """,
        node_role=NodeRole.ALL,
    ),
    # Step 5: Drop the old materialized view
    run_sql_with_exceptions(
        "DROP VIEW IF EXISTS query_log_archive_mv ON CLUSTER '{cluster}'",
        node_role=NodeRole.ALL,
    ),
    # Step 6: Rename tables (atomic swap)
    run_sql_with_exceptions(
        "RENAME TABLE query_log_archive TO query_log_archive_old, query_log_archive_new TO query_log_archive ON CLUSTER '{cluster}'",
        node_role=NodeRole.ALL,
    ),
    # Step 7: Rename the new materialized view
    run_sql_with_exceptions(
        "RENAME TABLE query_log_archive_new_mv TO query_log_archive_mv ON CLUSTER '{cluster}'",
        node_role=NodeRole.ALL,
    ),
    # Step 8: Drop the old table
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS query_log_archive_old ON CLUSTER '{cluster}'",
        node_role=NodeRole.ALL,
    ),
]
