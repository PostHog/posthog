from posthog.temporal.data_imports.cdc.activities import (
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
    validate_cdc_prerequisites_activity,
)
from posthog.temporal.data_imports.cdc.workflows import CDCExtractionWorkflow, CDCSlotCleanupWorkflow
from posthog.temporal.data_imports.cdp_producer_job import CDPProducerJobWorkflow, produce_to_cdp_kafka_activity
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    calculate_table_size_activity,
    check_billing_limits_activity,
    create_external_data_job_model_activity,
    create_source_templates,
    import_data_activity_sync,
    sync_new_schemas_activity,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)
from posthog.temporal.data_imports.signals.conversations_coordinator import (
    ConversationsSignalsCoordinatorWorkflow,
    EmitConversationsSignalsWorkflow,
    emit_conversations_signals_activity,
    get_conversations_signals_enabled_teams_activity,
)
from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    EmitDataImportSignalsWorkflow,
    emit_data_import_signals_activity,
)

WORKFLOWS = [ExternalDataJobWorkflow, CDPProducerJobWorkflow, CDCExtractionWorkflow, CDCSlotCleanupWorkflow]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity_sync,
    create_source_templates,
    check_billing_limits_activity,
    sync_new_schemas_activity,
    calculate_table_size_activity,
    trigger_schedule_buffer_one_activity,
    produce_to_cdp_kafka_activity,
    cdc_extract_activity,
    validate_cdc_prerequisites_activity,
    cleanup_orphan_slots_activity,
]

# Workflow + activities that run on the VIDEO_EXPORT_TASK_QUEUE (signals worker)
EMIT_SIGNALS_WORKFLOWS = [
    EmitDataImportSignalsWorkflow,
    ConversationsSignalsCoordinatorWorkflow,
    EmitConversationsSignalsWorkflow,
]
EMIT_SIGNALS_ACTIVITIES = [
    emit_data_import_signals_activity,
    emit_conversations_signals_activity,
    get_conversations_signals_enabled_teams_activity,
]
