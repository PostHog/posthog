"""Keeps a metric's node in the data modeling lineage graph in step with the metric itself."""

from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from posthog.hogql.database.database import Database

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.api import delete_metric_node, mark_metric_node_degraded, sync_metric_to_dag

from ..facade.enums import MARKDOWN_DEFINITION_KIND
from .validation import definition_nodes

if TYPE_CHECKING:
    from ..models.metric import Metric

logger = structlog.get_logger(__name__)

SYSTEM_TABLE_PREFIX = "system."

# An events node names an event, and an actions node names a stored filter over events. Both read
# the events table and nothing else a reader could open, so `events` is the whole upstream they add.
EVENT_SOURCE_KINDS = frozenset({"EventsNode", "ActionsNode"})
EVENTS_TABLE_NAME = "events"


class LineageSyncOutcome(StrEnum):
    SYNCED = "synced"
    REMOVED = "removed"
    DEGRADED = "degraded"


def has_executable_definition(metric: "Metric") -> bool:
    return metric.definition is not None and metric.definition_kind != MARKDOWN_DEFINITION_KIND


def dependency_names(metric: "Metric") -> list[str]:
    """The tables and views a metric reads, as lineage dependency names.

    Catalog metadata tables under `system.` are dropped: they describe the catalog rather than
    feeding the metric, and they have no node.
    """
    names = {name for name in metric.referenced_table_names or [] if not name.startswith(SYSTEM_TABLE_PREFIX)}
    if next(definition_nodes(metric.definition, EVENT_SOURCE_KINDS), None) is not None:
        names.add(EVENTS_TABLE_NAME)
    return sorted(names)


def sync_metric_lineage(metric: "Metric", database: Database | None = None) -> LineageSyncOutcome:
    """Bring the metric's lineage node in line with the metric, best effort.

    A lineage failure must never fail the write that triggered it, so everything here is caught and
    left on the node as a marker the graph can show. The outcome is returned rather than raised, so
    a caller running this over many metrics can report how many actually landed.
    """
    try:
        if metric.deleted or not has_executable_definition(metric):
            delete_metric_node(metric.team, metric.id)
            return LineageSyncOutcome.REMOVED
        sync_metric_to_dag(metric.team, metric.id, metric.name, dependency_names(metric), database=database)
        return LineageSyncOutcome.SYNCED
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to sync metric lineage", metric_id=str(metric.id), team_id=metric.team_id)
        try:
            mark_metric_node_degraded(metric.team, metric.id, metric.name, str(error))
        except Exception as marker_error:
            capture_exception(marker_error)
        return LineageSyncOutcome.DEGRADED


def remove_metric_lineage(metric: "Metric") -> None:
    """Drop the metric's lineage node. The metric row is already gone, so a failure here only
    strands a node the next backfill removes, and must not turn a successful delete into an error."""
    try:
        delete_metric_node(metric.team, metric.id)
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to remove metric lineage", metric_id=str(metric.id), team_id=metric.team_id)
