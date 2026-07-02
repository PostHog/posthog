"""
Facade for data_warehouse.

Re-exports the data-warehouse operational surface that sibling products and core
consume — temporal schedule/workflow management, S3 helpers, schema reconciliation,
job-status updates, and webhook ingestion. These cross the boundary as callables and
classes (operations on the import pipeline), not contract data.

Loaded lazily (PEP 562): the underlying logic modules pull heavy dependencies
(temporalio, s3fs) and sit in an import cycle with ``warehouse_sources`` (whose pipeline
imports this facade back). Resolving each name on first access — instead of importing
every logic module at module load — both breaks that import-time cycle and keeps this
module off the ``django.setup()`` path.
"""

_B = "products.data_warehouse.backend."

# symbol -> source module (relative to backend.)
_LAZY = {
    "CreateTableResult": "logic.data_load.create_table",
    "create_table_from_saved_query": "logic.data_load.create_table",
    "a_pause_saved_query_schedule": "logic.data_load.saved_query_service",
    "delete_saved_query_schedule": "logic.data_load.saved_query_service",
    "get_saved_query_schedule": "logic.data_load.saved_query_service",
    "pause_saved_query_schedule": "logic.data_load.saved_query_service",
    "saved_query_workflow_exists": "logic.data_load.saved_query_service",
    "sync_saved_query_workflow": "logic.data_load.saved_query_service",
    "trigger_saved_query_schedule": "logic.data_load.saved_query_service",
    "unpause_saved_query_schedule": "logic.data_load.saved_query_service",
    "a_unpause_external_data_schedule": "logic.data_load.service",
    "bulk_create_external_data_job_schedules": "logic.data_load.service",
    "bulk_delete_external_data_schedules": "logic.data_load.service",
    "cancel_external_data_workflow": "logic.data_load.service",
    "delete_cdc_extraction_schedule": "logic.data_load.service",
    "delete_discover_schemas_schedule": "logic.data_load.service",
    "delete_external_data_schedule": "logic.data_load.service",
    "ensure_cdc_slot_cleanup_schedule": "logic.data_load.service",
    "external_data_workflow_exists": "logic.data_load.service",
    "is_any_external_data_schema_paused": "logic.data_load.service",
    "is_cdc_enabled_for_team": "logic.data_load.service",
    "is_custom_source_ai_builder_enabled_for_team": "logic.data_load.service",
    "is_xmin_enabled_for_team": "logic.data_load.service",
    "pause_cdc_extraction_schedule": "logic.data_load.service",
    "pause_external_data_schedule": "logic.data_load.service",
    "sync_cdc_extraction_schedule": "logic.data_load.service",
    "sync_discover_schemas_schedule": "logic.data_load.service",
    "sync_external_data_job_workflow": "logic.data_load.service",
    "trigger_external_data_source_workflow": "logic.data_load.service",
    "trigger_external_data_workflow": "logic.data_load.service",
    "unpause_external_data_schedule": "logic.data_load.service",
    "create_warehouse_templates_for_source": "logic.data_load.source_templates",
    "update_external_job_status": "logic.external_data_source.jobs",
    "create_and_register_webhook": "logic.external_data_source.webhooks",
    "delete_webhook_and_hog_function": "logic.external_data_source.webhooks",
    "get_or_create_webhook_hog_function": "logic.external_data_source.webhooks",
    "get_webhook_url": "logic.external_data_source.webhooks",
    "reconcile_webhook_events": "logic.external_data_source.webhooks",
    "WebhookConsumerConfig": "logic.webhook_consumer.config",
    "WebhookS3Sink": "logic.webhook_consumer.consumer",
    "get_mysql_source_location": "mysql_helpers",
    "reconcile_mysql_schemas": "mysql_helpers",
    "reproject_direct_mysql_table": "mysql_helpers",
    "get_postgres_source_location": "postgres_helpers",
    "reconcile_postgres_schemas": "postgres_helpers",
    "reproject_direct_postgres_table": "postgres_helpers",
    "reconcile_snowflake_schemas": "snowflake_helpers",
    "reproject_direct_snowflake_table": "snowflake_helpers",
    "get_redshift_source_location": "redshift_helpers",
    "reconcile_redshift_schemas": "redshift_helpers",
    "reproject_direct_redshift_table": "redshift_helpers",
    "HogQLQueryFixerTool": "hogql_fixer_ai",
    "hide_direct_mysql_table": "direct_mysql",
    "upsert_direct_mysql_table": "direct_mysql",
    "hide_direct_postgres_table": "direct_postgres",
    "upsert_direct_postgres_table": "direct_postgres",
    "hide_direct_snowflake_table": "direct_snowflake",
    "upsert_direct_snowflake_table": "direct_snowflake",
    "hide_direct_redshift_table": "direct_redshift",
    "upsert_direct_redshift_table": "direct_redshift",
    "reconcile_refresh_name_substitutions": "postgres_warehouse_migration",
    "apply_on_refresh": "sql_warehouse_migration",
    "apply_on_schema_clear": "sql_warehouse_migration",
    "detect_schema_clear_transition": "sql_warehouse_migration",
    "is_multi_schema_capable_sql_source": "sql_warehouse_migration",
    "source_namespace_is_blank": "sql_warehouse_migration",
    "aget_s3_client": "s3",
    "ensure_bucket_exists": "s3",
    "get_s3_client": "s3",
    "get_size_of_folder": "s3",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
