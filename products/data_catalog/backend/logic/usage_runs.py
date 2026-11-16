"""Count the direct runs of a team's catalog metrics in a usage scan window.

The run event lands in PostHog's own telemetry project, not in the team's project, so the query
runs on the telemetry team and filters on the analyzed team's project group. Only runs from agent
surfaces count, because the section answers how agents use the catalog. A person who runs a metric
in the web app or through the API is not an agent run.
"""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.event_usage import AGENT_EVENT_SOURCES, EventSource
from posthog.models import Team

from ..facade.contracts import MetricRunCounts
from ..models import Metric
from .usage_snapshots import usage_snapshot_window, write_payload_sections

# The query has at most one row per live metric and agent surface. HogQL returns at most
# MAX_SELECT_RETURNED_ROWS rows, and a result at that cap can be missing rows, so the step fails
# instead of storing a partial count. groupUniqArray caps each row's people so one popular metric
# cannot pull an unbounded set into memory. A capped row can only understate a displayed people count.
_MAX_RUNS_ROWS = MAX_SELECT_RETURNED_ROWS
_RUNS_QUERY = """
SELECT
    properties.metric_id AS metric_id,
    properties.source AS source,
    count() AS runs,
    groupUniqArray(1000)(distinct_id) AS people
FROM events
WHERE event = 'data catalog metric run'
    AND timestamp >= {window_start}
    AND timestamp < {window_end}
    AND properties.$groups.project = {team_uuid}
    AND ifNull(toString(properties.was_impersonated), '') != 'true'
    AND properties.source IN {agent_sources}
    AND properties.metric_id IN {metric_ids}
GROUP BY metric_id, source
LIMIT {row_limit}
"""


class MetricRunsTruncated(Exception):
    """The run count query reached its row limit, so the counts are not complete."""


def count_metric_runs(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> list[MetricRunCounts]:
    # The event can carry a deleted metric or another team's metric id, so the query keeps only live ids.
    live_ids = set(Metric.objects.for_team(team.id).filter(deleted=False).values_list("id", flat=True))
    if not live_ids:
        return []

    # One row more than the bound, so only a result that the cap cuts short reaches the limit.
    row_limit = min(len(live_ids) * len(AGENT_EVENT_SOURCES) + 1, _MAX_RUNS_ROWS)
    with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT):
        response = execute_hogql_query(
            query=parse_select(_RUNS_QUERY),
            team=telemetry_team,
            placeholders={
                "window_start": ast.Constant(value=window_start),
                "window_end": ast.Constant(value=window_end),
                "team_uuid": ast.Constant(value=str(team.uuid)),
                "row_limit": ast.Constant(value=row_limit),
                "agent_sources": ast.Tuple(
                    exprs=[ast.Constant(value=source.value) for source in sorted(AGENT_EVENT_SOURCES)]
                ),
                "metric_ids": ast.Tuple(
                    exprs=[ast.Constant(value=str(metric_id)) for metric_id in sorted(live_ids, key=str)]
                ),
            },
            query_type="DataCatalogUsageMetricRuns",
            workload=Workload.OFFLINE,
            # A profile that breaks on timeout returns partial counts with no error, so the step fails instead.
            settings=HogQLGlobalSettings(timeout_overflow_mode="throw"),
        )

    rows = response.results or []
    if len(rows) >= row_limit:
        raise MetricRunsTruncated(f"The metric run query returned {len(rows)} rows, which is its limit.")

    direct_runs: dict[UUID, dict[str, int]] = defaultdict(dict)
    people: dict[UUID, set[str]] = defaultdict(set)
    scout_runs: dict[UUID, int] = defaultdict(int)

    for raw_metric_id, source, runs, distinct_ids in rows:
        metric_id = _parse_uuid(raw_metric_id)
        if metric_id is None or metric_id not in live_ids:
            continue
        # Scouts can run one metric many times a day, so their runs stay out of the headline counts.
        if source == EventSource.SELF_DRIVING:
            scout_runs[metric_id] += runs
            continue
        direct_runs[metric_id][source] = direct_runs[metric_id].get(source, 0) + runs
        people[metric_id].update(distinct_ids)

    return [
        MetricRunCounts(
            metric_id=metric_id,
            direct_runs=direct_runs.get(metric_id, {}),
            direct_people=len(people.get(metric_id, set())),
            scout_runs=scout_runs.get(metric_id, 0),
        )
        for metric_id in sorted({*direct_runs, *scout_runs}, key=str)
    ]


def _parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def collect_metric_runs_into_snapshot(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> int:
    """Count the window's direct runs and write them as the snapshot's ``metric_runs`` section."""
    team = Team.objects.get(id=team_id)
    telemetry_team = Team.objects.get(id=telemetry_team_id)
    window = usage_snapshot_window(team_id, snapshot_id)
    counts = count_metric_runs(
        team=team, telemetry_team=telemetry_team, window_start=window.start, window_end=window.end
    )
    write_payload_sections(team_id, snapshot_id, metric_runs=counts)
    return len(counts)
