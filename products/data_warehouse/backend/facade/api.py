"""
Facade for data_warehouse.

Re-exports the data-warehouse operational surface that sibling products and core
consume — temporal schedule/workflow management, S3 helpers, schema reconciliation,
job-status updates, and webhook ingestion. These cross the boundary as callables and
classes (operations on the import pipeline), not contract data.

This module pulls heavy dependencies (temporalio, s3fs) via the re-exported logic, so
it must only be imported off the ``django.setup()`` path — its consumers are the
temporal workers and import-pipeline code. Light, setup-path surfaces live in the
sibling facade submodules (``facade.sources`` constants, ``facade.models``,
``facade.hogql``, ``facade.tasks``).
"""

from products.data_warehouse.backend.logic.data_load.create_table import (
    CreateTableResult,
    create_table_from_saved_query,
)
from products.data_warehouse.backend.logic.data_load.saved_query_service import (
    a_pause_saved_query_schedule,
    delete_saved_query_schedule,
    get_saved_query_schedule,
    pause_saved_query_schedule,
    saved_query_workflow_exists,
    sync_saved_query_workflow,
    trigger_saved_query_schedule,
    unpause_saved_query_schedule,
)
from products.data_warehouse.backend.logic.data_load.service import (
    a_unpause_external_data_schedule,
    delete_cdc_extraction_schedule,
    delete_discover_schemas_schedule,
    delete_external_data_schedule,
    external_data_workflow_exists,
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    unpause_external_data_schedule,
)
from products.data_warehouse.backend.logic.data_load.source_templates import create_warehouse_templates_for_source
from products.data_warehouse.backend.logic.external_data_source.jobs import update_external_job_status
from products.data_warehouse.backend.logic.webhook_consumer.config import WebhookConsumerConfig
from products.data_warehouse.backend.logic.webhook_consumer.consumer import WebhookS3Sink
from products.data_warehouse.backend.mysql_helpers import reconcile_mysql_schemas
from products.data_warehouse.backend.postgres_helpers import reconcile_postgres_schemas
from products.data_warehouse.backend.s3 import aget_s3_client, ensure_bucket_exists, get_s3_client, get_size_of_folder

__all__ = [
    "CreateTableResult",
    "WebhookConsumerConfig",
    "WebhookS3Sink",
    "a_pause_saved_query_schedule",
    "a_unpause_external_data_schedule",
    "aget_s3_client",
    "create_table_from_saved_query",
    "create_warehouse_templates_for_source",
    "delete_cdc_extraction_schedule",
    "delete_discover_schemas_schedule",
    "delete_external_data_schedule",
    "delete_saved_query_schedule",
    "ensure_bucket_exists",
    "external_data_workflow_exists",
    "get_s3_client",
    "get_saved_query_schedule",
    "get_size_of_folder",
    "pause_external_data_schedule",
    "pause_saved_query_schedule",
    "reconcile_mysql_schemas",
    "reconcile_postgres_schemas",
    "saved_query_workflow_exists",
    "sync_external_data_job_workflow",
    "sync_saved_query_workflow",
    "trigger_external_data_workflow",
    "trigger_saved_query_schedule",
    "unpause_external_data_schedule",
    "unpause_saved_query_schedule",
    "update_external_job_status",
]
