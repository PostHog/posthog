from posthog.temporal.data_modeling.activities import (
    check_duckgres_shadow_enabled_activity,
    create_data_modeling_job_activity,
    enrich_view_semantics_activity,
    fail_materialization_activity,
    get_dag_structure_activity,
    materialize_view_activity,
    materialize_view_duckgres_activity,
    preempt_dag_run_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
)
from posthog.temporal.data_modeling.run_workflow import (
    RunWorkflow,
    build_dag_activity,
    cancel_jobs_activity,
    cleanup_running_jobs_activity,
    create_job_model_activity,
    fail_jobs_activity,
    finish_run_activity,
    run_dag_activity,
    start_run_activity,
)
from posthog.temporal.data_modeling.workflows import (
    EnrichViewSemanticsWorkflow,
    ExecuteDAGWorkflow,
    MaterializeViewWorkflow,
)

WORKFLOWS = [RunWorkflow, MaterializeViewWorkflow, ExecuteDAGWorkflow]

# Semantic enrichment is LLM work that must not contend with materialization slots, so it runs on the
# metadata queue rather than the materialization queues. Kept as separate lists (NOT folded into
# WORKFLOWS/ACTIVITIES above) so start_temporal_worker registers it only on the metadata queue.
SEMANTIC_ENRICHMENT_WORKFLOWS = [EnrichViewSemanticsWorkflow]
SEMANTIC_ENRICHMENT_ACTIVITIES = [enrich_view_semantics_activity]
ACTIVITIES = [
    check_duckgres_shadow_enabled_activity,
    create_data_modeling_job_activity,
    get_dag_structure_activity,
    fail_materialization_activity,
    materialize_view_activity,
    materialize_view_duckgres_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
    finish_run_activity,
    start_run_activity,
    build_dag_activity,
    run_dag_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    cleanup_running_jobs_activity,
    preempt_dag_run_activity,
]
