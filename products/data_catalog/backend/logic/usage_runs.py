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
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.event_usage import AGENT_EVENT_SOURCES
from posthog.models import Team

from ..facade.contracts import MetricRunCounts
from ..facade.enums import SCOUT_SOURCE
from ..models import Metric
from .usage_snapshots import usage_snapshot_window, write_payload_sections

# A metric runs from a handful of surfaces, so the LIMIT bounds metrics times surfaces with room to
# spare. groupUniqArray caps each row's people so one popular metric cannot pull an unbounded set into
# memory. A capped row can only understate a displayed people count.
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
GROUP BY metric_id, source
LIMIT 10000
"""


def count_metric_runs(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> list[MetricRunCounts]:
    with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
        response = execute_hogql_query(
            query=parse_select(_RUNS_QUERY),
            team=telemetry_team,
            placeholders={
                "window_start": ast.Constant(value=window_start),
                "window_end": ast.Constant(value=window_end),
                "team_uuid": ast.Constant(value=str(team.uuid)),
                "agent_sources": ast.Tuple(
                    exprs=[ast.Constant(value=source.value) for source in sorted(AGENT_EVENT_SOURCES)]
                ),
            },
            query_type="DataCatalogUsageMetricRuns",
            workload=Workload.OFFLINE,
        )

    live_ids = set(Metric.objects.for_team(team.id).filter(deleted=False).values_list("id", flat=True))
    direct_runs: dict[UUID, dict[str, int]] = defaultdict(dict)
    people: dict[UUID, set[str]] = defaultdict(set)
    scout_runs: dict[UUID, int] = defaultdict(int)

    for raw_metric_id, source, runs, distinct_ids in response.results or []:
        metric_id = _parse_uuid(raw_metric_id)
        if metric_id is None or metric_id not in live_ids:
            continue
        if source == SCOUT_SOURCE:
            scout_runs[metric_id] += runs
            continue
        surface = source or "unknown"
        direct_runs[metric_id][surface] = direct_runs[metric_id].get(surface, 0) + runs
        people[metric_id].update(distinct_ids)

    return [
        MetricRunCounts(
            metric_id=metric_id,
            direct_runs=direct_runs.get(metric_id, {}),
            direct_people=len(people.get(metric_id, set())),
            scout_runs=scout_runs.get(metric_id, 0),
            # Source insight calculations come from the query log, which this step does not read.
            source_insight_dashboard_runs=0,
            source_insight_insight_runs=0,
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
