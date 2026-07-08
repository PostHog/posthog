"""Facade over logic/fleet_ops.py and the fleet slice of logic/schedule_truth.py for the
data_modeling_ops cross-team internal API. Consumed by this product's presentation layer
and the endpoints product's internal ops views."""

from products.data_modeling.backend.logic.fleet_ops import (
    FAILING_SAVED_QUERY_CAP,
    classify_migration,
    dag_ids_by_team,
    failing_saved_query_rows,
    find_duplicate_backing_tables,
    find_multi_dag_saved_queries,
    find_orphaned_schedules,
    find_unscheduled_entities,
    group_failing_by_schedule,
    modeling_team_ids,
    resolve_entity,
    team_activity_rows,
)
from products.data_modeling.backend.logic.schedule_truth import list_data_modeling_schedules

__all__ = [
    "FAILING_SAVED_QUERY_CAP",
    "classify_migration",
    "dag_ids_by_team",
    "failing_saved_query_rows",
    "find_duplicate_backing_tables",
    "find_multi_dag_saved_queries",
    "find_orphaned_schedules",
    "find_unscheduled_entities",
    "group_failing_by_schedule",
    "list_data_modeling_schedules",
    "modeling_team_ids",
    "resolve_entity",
    "team_activity_rows",
]
