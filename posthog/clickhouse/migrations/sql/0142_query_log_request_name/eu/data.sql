ALTER TABLE query_log_archive ADD COLUMN IF NOT EXISTS lc_request_name String AFTER lc_name

ALTER TABLE query_log_archive_mv MODIFY QUERY

SELECT
    hostname,
    user,
    query_id,
    initial_query_id,
    is_initial_query,
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

    ProfileEvents['RealTimeMicroseconds'] as ProfileEvents_RealTimeMicroseconds,
    ProfileEvents['OSCPUVirtualTimeMicroseconds'] as ProfileEvents_OSCPUVirtualTimeMicroseconds,

    ProfileEvents['S3Clients'] as ProfileEvents_S3Clients,
    ProfileEvents['S3DeleteObjects'] as ProfileEvents_S3DeleteObjects,
    ProfileEvents['S3CopyObject'] as ProfileEvents_S3CopyObject,
    ProfileEvents['S3ListObjects'] as ProfileEvents_S3ListObjects,
    ProfileEvents['S3HeadObject'] as ProfileEvents_S3HeadObject,
    ProfileEvents['S3GetObjectAttributes'] as ProfileEvents_S3GetObjectAttributes,
    ProfileEvents['S3CreateMultipartUpload'] as ProfileEvents_S3CreateMultipartUpload,
    ProfileEvents['S3UploadPartCopy'] as ProfileEvents_S3UploadPartCopy,
    ProfileEvents['S3UploadPart'] as ProfileEvents_S3UploadPart,
    ProfileEvents['S3AbortMultipartUpload'] as ProfileEvents_S3AbortMultipartUpload,
    ProfileEvents['S3CompleteMultipartUpload'] as ProfileEvents_S3CompleteMultipartUpload,
    ProfileEvents['S3PutObject'] as ProfileEvents_S3PutObject,
    ProfileEvents['S3GetObject'] as ProfileEvents_S3GetObject,
    ProfileEvents['ReadBufferFromS3Bytes'] as ProfileEvents_ReadBufferFromS3Bytes,
    ProfileEvents['WriteBufferFromS3Bytes'] as ProfileEvents_WriteBufferFromS3Bytes,

    ProfileEvents,

    JSONExtractString(log_comment, 'workflow') as lc_workflow,
    JSONExtractString(log_comment, 'kind') as lc_kind,
    JSONExtractString(log_comment, 'id') as lc_id,
    JSONExtractString(log_comment, 'route_id') as lc_route_id,

    JSONExtractString(log_comment, 'access_method') as lc_access_method,
    JSONExtractString(log_comment, 'api_key_label') as lc_api_key_label,
    JSONExtractString(log_comment, 'api_key_mask') as lc_api_key_mask,

    JSONExtractString(log_comment, 'query_type') as lc_query_type,
    JSONExtractString(log_comment, 'product') as lc_product,
    JSONExtractInt(log_comment, 'chargeable') == 1 as lc_chargeable,
    JSONExtractString(log_comment, 'name') as lc_name,
    JSONExtractString(log_comment, 'request_name') as lc_request_name,
    JSONExtractString(log_comment, 'client_query_id') as lc_client_query_id,

    JSONExtractString(log_comment, 'org_id') as lc_org_id,
    JSONExtractInt(log_comment, 'team_id') as team_id,
    JSONExtractInt(log_comment, 'user_id') as lc_user_id,
    JSONExtractBool(log_comment, 'is_impersonated') as lc_is_impersonated,
    JSONExtractString(log_comment, 'session_id') as lc_session_id,

    JSONExtractInt(log_comment, 'dashboard_id') as lc_dashboard_id,
    JSONExtractInt(log_comment, 'insight_id') as lc_insight_id,
    JSONExtractInt(log_comment, 'cohort_id') as lc_cohort_id,
    JSONExtractString(log_comment, 'batch_export_id') as lc_batch_export_id,
    JSONExtractInt(log_comment, 'experiment_id') as lc_experiment_id,
    JSONExtractString(log_comment, 'experiment_feature_flag_key') as lc_experiment_feature_flag_key,

    JSONExtractString(log_comment, 'alert_config_id') as lc_alert_config_id,
    JSONExtractString(log_comment, 'feature') as lc_feature,
    JSONExtractString(log_comment, 'table_id') as lc_table_id,
    JSONExtractInt(log_comment, 'warehouse_query') == 1 as lc_warehouse_query,
    JSONExtractString(log_comment, 'person_on_events_mode') as lc_person_on_events_mode,
    JSONExtractString(log_comment, 'service_name') as lc_service_name,
    JSONExtractString(log_comment, 'workload') as lc_workload,

    -- for entries with 'query' tag, some queries have source, we should use this
    if(JSONHas(log_comment, 'query', 'source'),
        JSONExtractString(log_comment, 'query', 'source', 'kind'),
        JSONExtractString(log_comment, 'query', 'kind')) as lc_query__kind,
    multiIf(not is_initial_query, '',
        JSONHas(log_comment, 'query', 'source'), JSONExtractString(log_comment, 'query', 'source', 'query'),
        JSONExtractString(log_comment, 'query', 'query')) as lc_query__query,
    if(is_initial_query, JSONExtractRaw(log_comment, 'query'), '') as lc_query,

    JSONExtractString(log_comment, 'temporal', 'workflow_namespace') as lc_temporal__workflow_namespace,
    JSONExtractString(log_comment, 'temporal', 'workflow_type') as lc_temporal__workflow_type,
    JSONExtractString(log_comment, 'temporal', 'workflow_id') as lc_temporal__workflow_id,
    JSONExtractString(log_comment, 'temporal', 'workflow_run_id') as lc_temporal__workflow_run_id,
    JSONExtractString(log_comment, 'temporal', 'activity_type') as lc_temporal__activity_type,
    JSONExtractString(log_comment, 'temporal', 'activity_id') as lc_temporal__activity_id,
    JSONExtractInt(log_comment, 'temporal', 'attempt') as lc_temporal__attempt,

    JSONExtractString(log_comment, 'dagster', 'job_name') as lc_dagster__job_name,
    JSONExtractString(log_comment, 'dagster', 'run_id') as lc_dagster__run_id,
    JSONExtractString(log_comment, 'dagster', 'tags', 'owner') as lc_dagster__owner,

    if(is_initial_query, JSONExtractRaw(log_comment, 'modifiers'), '') as lc_modifiers
FROM system.query_log
WHERE
    type != 'QueryStart'
