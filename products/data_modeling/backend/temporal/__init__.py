from typing import TYPE_CHECKING

from products.data_modeling.backend.temporal.activities import (
    check_managed_warehouse_shadow_eligibility_activity,
    check_managed_warehouse_shadow_enabled_activity,
    check_team_managed_warehouse_shadow_eligibility_activity,
    clear_cdp_staging_activity,
    create_data_modeling_job_activity,
    enrich_view_semantics_activity,
    fail_materialization_activity,
    get_clickhouse_kill_switch_level_activity,
    get_dag_structure_activity,
    materialize_view_activity,
    materialize_view_managed_warehouse_activity,
    notify_dag_materialization_failures_activity,
    preempt_dag_run_activity,
    prepare_queryable_table_activity,
    publish_queryable_table_activity,
    quality_block_materialization_activity,
    record_skipped_data_modeling_jobs_activity,
    stage_queryable_files_activity,
    succeed_materialization_activity,
)
from products.data_modeling.backend.temporal.workflows import (
    EnrichViewSemanticsWorkflow,
    ExecuteDAGWorkflow,
    MaterializeViewWorkflow,
)

from .activities.notebook_model import (
    fail_notebook_model,
    prepare_notebook_model,
    publish_notebook_model,
    remove_retired_notebook_upload,
)
from .workflows.notebook_model import MaterializeNotebookWorkflow, RetireNotebookUploadWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [MaterializeViewWorkflow, ExecuteDAGWorkflow, MaterializeNotebookWorkflow, RetireNotebookUploadWorkflow]

# Semantic enrichment is LLM work that must not contend with materialization slots, so it runs on the
# metadata queue rather than the materialization queues. Kept as separate lists (NOT folded into
# WORKFLOWS/ACTIVITIES above) so start_temporal_worker registers it only on the metadata queue.
SEMANTIC_ENRICHMENT_WORKFLOWS = [EnrichViewSemanticsWorkflow]
SEMANTIC_ENRICHMENT_ACTIVITIES: list[ActivityDefinition] = [enrich_view_semantics_activity]
ACTIVITIES: list[ActivityDefinition] = [
    prepare_notebook_model,
    publish_notebook_model,
    remove_retired_notebook_upload,
    fail_notebook_model,
    check_managed_warehouse_shadow_eligibility_activity,
    check_managed_warehouse_shadow_enabled_activity,
    check_team_managed_warehouse_shadow_eligibility_activity,
    clear_cdp_staging_activity,
    create_data_modeling_job_activity,
    record_skipped_data_modeling_jobs_activity,
    get_clickhouse_kill_switch_level_activity,
    get_dag_structure_activity,
    fail_materialization_activity,
    materialize_view_activity,
    materialize_view_managed_warehouse_activity,
    prepare_queryable_table_activity,
    publish_queryable_table_activity,
    quality_block_materialization_activity,
    stage_queryable_files_activity,
    succeed_materialization_activity,
    preempt_dag_run_activity,
    notify_dag_materialization_failures_activity,
]
