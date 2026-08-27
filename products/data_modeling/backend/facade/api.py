"""
Facade for data_modeling.

Re-exports the saved-query / DAG operational services that sibling products and core
consume. Loaded lazily (PEP 562): the underlying services pull heavy dependencies
(HogQL, temporal) and sit alongside the warehouse import pipeline, so resolving each
name on first access keeps this module off the ``django.setup()`` path.
"""

_B = "products.data_modeling.backend."

_LAZY = {
    "UnsatisfiableFrequencyError": "logic.freshness",
    "UnsupportedFrequencyTargetError": "logic.freshness",
    "humanize_cadence": "logic.freshness",
    "HasDependentsError": "logic.saved_query_dag_sync",
    "delete_node_from_dag": "logic.saved_query_dag_sync",
    "promote_view_nodes_to_matview": "logic.saved_query_dag_sync",
    "sync_saved_query_to_dag": "logic.saved_query_dag_sync",
    "update_node_type": "logic.saved_query_dag_sync",
    "SavedQueryNotFoundError": "logic.node_materialization",
    "SavedQueryNotOnV2ScheduleError": "logic.node_materialization",
    "is_saved_query_on_v2_schedule": "logic.node_materialization",
    "materialize_saved_query": "logic.node_materialization",
    "run_saved_query_materialization": "logic.node_materialization",
    "get_materialized_table_uri": "logic.saved_query_reads",
    "get_node_ids_for_saved_queries": "logic.saved_query_reads",
    "get_saved_query_columns": "logic.saved_query_reads",
    "get_saved_query_ids_for_nodes": "logic.saved_query_reads",
    "get_saved_query_summary": "logic.saved_query_reads",
    "saved_query_materialized_at": "logic.saved_query_freshness",
    "start_node_materialization": "logic.node_materialization",
    "delete_dag_schedules": "logic.schedule_reconcile",
    "delete_team_data_modeling_schedules": "logic.schedule_reconcile",
    "apply_saved_query_frequency_anchor": "logic.schedule_reconcile",
    "apply_saved_query_frequency_target": "logic.schedule_reconcile",
    "check_saved_query_frequency_target": "logic.schedule_reconcile",
    "tiered_schedules_enabled": "logic.schedule_reconcile",
    "declared_targets_by_saved_query": "logic.node_frequency",
    "get_declared_target": "logic.node_frequency",
    "saved_query_target_bounds": "logic.node_frequency",
    "clear_node_suspension": "logic.node_suspension",
    "is_node_suspended": "logic.node_suspension",
    "mark_node_suspended": "logic.node_suspension",
    "query_fingerprint": "logic.node_suspension",
    "resume_nodes": "logic.node_suspension",
    "resume_saved_query": "logic.node_suspension",
    "suspension_reset_at": "logic.node_suspension",
    "suspension_state": "logic.node_suspension",
    "suspension_state_for_saved_query": "logic.node_suspension",
    "compute_enrichment_hash": "logic.enrich_view_semantics",
    "enrichment_gates_pass": "logic.enrich_view_semantics",
    "enrich_view_semantics_sync": "logic.enrich_view_semantics",
    "MAX_LOOKBACK_SECONDS": "logic.incremental",
    "IncrementalConfig": "logic.incremental",
    "IncrementalState": "logic.incremental",
    "clear_incremental_state": "logic.incremental",
    "definition_fingerprint": "logic.incremental",
    "deserialize_watermark": "logic.incremental",
    "get_incremental_config": "logic.incremental",
    "get_incremental_state": "logic.incremental",
    "set_incremental_state": "logic.incremental",
    "window_start": "logic.incremental",
    "IncrementalFilterError": "logic.incremental_filter",
    "inject_incremental_filter": "logic.incremental_filter",
    "EligibilityResult": "logic.incremental_eligibility",
    "check_incremental_eligibility": "logic.incremental_eligibility",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
