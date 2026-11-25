from typing import TYPE_CHECKING

from .activities import (
    collect_metric_runs,
    collect_table_sources,
    collect_topics,
    create_snapshot,
    detect_adjusted_runs,
    finalize_snapshot,
    find_uncovered,
    list_teams_due,
    stitch_sessions,
)
from .workflows import DataCatalogUsageScanWorkflow, DataCatalogUsageScheduleWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [DataCatalogUsageScanWorkflow, DataCatalogUsageScheduleWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    list_teams_due,
    create_snapshot,
    collect_metric_runs,
    stitch_sessions,
    detect_adjusted_runs,
    collect_topics,
    collect_table_sources,
    find_uncovered,
    finalize_snapshot,
]
