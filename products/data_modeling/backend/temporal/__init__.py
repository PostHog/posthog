from products.data_modeling.backend.temporal.activities import (
    copy_to_ducklake_activity,
    create_materialization_job_activity,
    fail_materialization_activity,
    finish_materialization_activity,
    get_dag_structure_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
)
from products.data_modeling.backend.temporal.workflows import ExecuteDAGWorkflow, MaterializeViewWorkflow

WORKFLOWS = [MaterializeViewWorkflow]

ACTIVITIES = [
    create_materialization_job_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    copy_to_ducklake_activity,
    finish_materialization_activity,
    fail_materialization_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ExecuteDAGWorkflow",
    "MaterializeViewWorkflow",
    "copy_to_ducklake_activity",
    "create_materialization_job_activity",
    "fail_materialization_activity",
    "finish_materialization_activity",
    "get_dag_structure_activity",
    "materialize_view_activity",
    "prepare_queryable_table_activity",
]
