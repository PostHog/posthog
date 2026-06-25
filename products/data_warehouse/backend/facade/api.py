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
    "delete_cdc_extraction_schedule": "logic.data_load.service",
    "delete_discover_schemas_schedule": "logic.data_load.service",
    "delete_external_data_schedule": "logic.data_load.service",
    "external_data_workflow_exists": "logic.data_load.service",
    "pause_external_data_schedule": "logic.data_load.service",
    "sync_external_data_job_workflow": "logic.data_load.service",
    "trigger_external_data_workflow": "logic.data_load.service",
    "unpause_external_data_schedule": "logic.data_load.service",
    "create_warehouse_templates_for_source": "logic.data_load.source_templates",
    "update_external_job_status": "logic.external_data_source.jobs",
    "WebhookConsumerConfig": "logic.webhook_consumer.config",
    "WebhookS3Sink": "logic.webhook_consumer.consumer",
    "reconcile_mysql_schemas": "mysql_helpers",
    "reconcile_postgres_schemas": "postgres_helpers",
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
