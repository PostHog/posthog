"""Keeps a metric's node in the data modeling lineage graph in step with the metric itself."""

from enum import StrEnum

from django.db import transaction

import structlog

from posthog.hogql.database.database import Database

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import team_scope

from products.data_modeling.backend.facade.api import delete_metric_node, mark_metric_node_degraded, sync_metric_to_dag
from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES

from ..facade.enums import HOGQL_DEFINITION_KIND, MARKDOWN_DEFINITION_KIND
from ..models.metric import Metric
from .validation import definition_nodes, table_names_as_written

logger = structlog.get_logger(__name__)

SYSTEM_TABLE_PREFIX = "system."

# An events node names an event, and an actions node names a stored filter over events. Both read
# the events table and nothing else a reader could open, so `events` is the whole upstream they add.
EVENT_SOURCE_KINDS = frozenset({"EventsNode", "ActionsNode"})
EVENTS_TABLE_NAME = "events"


class LineageSyncOutcome(StrEnum):
    SYNCED = "synced"
    # The node is written and its other edges are in place, but a dependency name matched no node,
    # so the metric is missing that edge and carries the unresolved marker. A later write to the
    # metric, or the backfill, links it once the missing node exists.
    UNRESOLVED = "unresolved"
    REMOVED = "removed"
    DEGRADED = "degraded"


def has_executable_definition(metric: Metric) -> bool:
    return metric.definition is not None and metric.definition_kind != MARKDOWN_DEFINITION_KIND


def _referenced_names(metric: Metric) -> list[str]:
    """What the metric reads, by the names its own definition uses.

    ``referenced_table_names`` is collected after the query is resolved, and resolution replaces a
    non-materialized view with its body, so the view's name is not in there. Every other definition
    kind records direct references already, so it keeps using the field.
    """
    if metric.definition_kind == HOGQL_DEFINITION_KIND and metric.definition:
        return table_names_as_written(metric.definition)
    return metric.referenced_table_names or []


def dependency_names(metric: Metric) -> list[str]:
    """The tables and views a metric reads, as lineage dependency names.

    Catalog metadata tables under `system.` are dropped: they describe the catalog rather than
    feeding the metric, and they have no node.
    """
    names = {name for name in _referenced_names(metric) if not name.startswith(SYSTEM_TABLE_PREFIX)}
    if next(definition_nodes(metric.definition, EVENT_SOURCE_KINDS), None) is not None:
        names.add(EVENTS_TABLE_NAME)
    return sorted(names)


def sync_metric_lineage(metric: Metric, database: Database | None = None) -> LineageSyncOutcome:
    """Bring the metric's lineage node in line with the metric, best effort.

    `metric` may be minutes old: the caller reads it, then the schema build below takes far longer
    than the write that scheduled this. The row is read again under a lock once the schema is ready,
    so a metric deleted or rewritten in the meantime decides the outcome rather than the stale copy.

    A lineage failure must never fail the write that triggered it, so everything here is caught and
    left on the node as a marker the graph can show. The outcome is returned rather than raised, so
    a caller running this over many metrics can report how many actually landed.
    """
    try:
        if metric.deleted or not has_executable_definition(metric):
            delete_metric_node(metric.team, metric.id)
            return LineageSyncOutcome.REMOVED
        if database is None:
            database = Database.create_for(
                team=metric.team,
                bypass_warehouse_access_control=True,
                allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
            )
        with team_scope(metric.team_id), transaction.atomic():
            current = Metric.objects.for_team(metric.team_id).select_for_update().filter(pk=metric.pk).first()
            if current is None or current.deleted or not has_executable_definition(current):
                delete_metric_node(metric.team, metric.id)
                return LineageSyncOutcome.REMOVED
            unresolved = sync_metric_to_dag(
                metric.team, current.id, current.name, dependency_names(current), database=database
            )
        return LineageSyncOutcome.UNRESOLVED if unresolved else LineageSyncOutcome.SYNCED
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to sync metric lineage", metric_id=str(metric.id), team_id=metric.team_id)
        try:
            mark_metric_node_degraded(metric.team, metric.id, metric.name, str(error))
        except Exception as marker_error:
            capture_exception(marker_error)
        return LineageSyncOutcome.DEGRADED


def remove_metric_lineage(metric: Metric) -> None:
    """Drop the metric's lineage node. The metric row is already gone, so a failure here only
    strands a node the next backfill removes, and must not turn a successful delete into an error."""
    try:
        delete_metric_node(metric.team, metric.id)
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to remove metric lineage", metric_id=str(metric.id), team_id=metric.team_id)
