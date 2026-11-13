"""Find the agent queries that re-derive a catalog metric instead of running it.

The agent SQL and the catalog tool calls both come from the MCP telemetry in PostHog's own project.
A fingerprint match nominates a pair, the judge decides it, and the session's earlier catalog calls
say whether the agent read the metric first.
"""

import json
import asyncio
import hashlib
import dataclasses
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timedelta
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import Team
from posthog.sync import database_sync_to_async

from ..facade.contracts import AdjustedRun
from ..facade.enums import HOGQL_DEFINITION_KIND, SCOUT_SOURCE, JudgeRelation, ShapeOutcome
from ..models import Metric
from .agent_sessions import CATALOG_CALL_LOOKBACK, stored_conversations
from .measure_fingerprint import MeasureExtractionError, extract_measures
from .metric_fingerprint import CatalogIndex, definition_to_hogql
from .usage_judge import JudgeVerdict, MetricBrief, judge_pair, require_ai_consent
from .usage_snapshots import STORED_SQL_CHARS, usage_snapshot_window, write_payload_sections

logger = structlog.get_logger(__name__)

# Bounds one scan's judge spend while its precision is measured.
JUDGE_CALL_CAP = 12000

# The snapshot keeps one run per occurrence, so a long query must not grow the payload row without bound.
_STORED_TEXT_CHARS = STORED_SQL_CHARS

# Repeated matching queries share one judged group, so the group cap does not bound the occurrences.
_MAX_STORED_RUNS = 5000

# At this concurrency a scan that reaches the cap finishes inside the step's two-hour timeout.
_JUDGE_CONCURRENCY = 24

# Each failed call drops its pair from the section, so above this share the section would undercount
# re-derivations without a sign.
_MAX_FAILED_SHARE = 0.1

_DESCRIBE_TOOLS = frozenset({"metric-describe", "data-catalog-metric-run"})

# The page is a day so the scan stays under the HogQL row cap as traffic grows. A full page can be
# missing rows, so it splits in half until a page holds all of its rows. A full page at the floor
# fails the step, because a partial scan would undercount re-derivations without a sign.
_PAGE = timedelta(days=1)
_MIN_PAGE = timedelta(hours=1)
_PAGE_ROW_LIMIT = 50000

# Trace ids come from `events`, which is ordered by time, because `ai_events` is ordered by trace and
# a time filter alone would scan every trace of the telemetry team.
_AGENT_SQL_QUERY = """
SELECT
    a.timestamp,
    a.trace_id,
    a.distinct_id,
    JSONExtractString(ifNull(a.input, ''), 1, 'content') AS intent,
    JSONExtractString(ifNull(a.output_choices, ''), 1, 'content') AS sql,
    toString(a.properties.source) AS source
FROM posthog.ai_events AS a
WHERE a.event = '$ai_generation'
    AND a.span_name = 'execute-sql'
    AND a.is_error = 0
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event = '$ai_generation'
            AND properties.$ai_span_name = 'execute-sql'
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
    )
LIMIT {row_limit}
"""

# `input_state` holds the tool arguments as a JSON string, so the metric name sits one decode down.
_CATALOG_CALLS_QUERY = """
SELECT
    a.trace_id,
    a.timestamp,
    a.span_name,
    JSONExtractString(JSONExtractString(ifNull(a.input_state, '')), 'name') AS metric_name
FROM posthog.ai_events AS a
WHERE a.event = '$ai_span'
    AND a.is_error = 0
    AND a.span_name IN ('metric-describe', 'data-catalog-metric-run')
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event = '$ai_span'
            AND properties.$ai_span_name IN ('metric-describe', 'data-catalog-metric-run')
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
    )
LIMIT {row_limit}
"""


@frozen
class AgentQuery:
    occurred_at: datetime
    trace_id: str
    distinct_id: str
    intent: str
    sql: str
    is_scout: bool


@frozen
class CatalogCall:
    trace_id: str
    occurred_at: datetime
    tool: str
    metric_name: str


@frozen
class CandidateGroup:
    """Every run of one SQL text that one metric's fingerprint nominated. The judge reads it once."""

    metric_id: UUID
    sql: str
    intent: str
    occurrences: tuple[AgentQuery, ...]

    @property
    def scout_only(self) -> bool:
        return all(occurrence.is_scout for occurrence in self.occurrences)


@frozen
class JudgeSelection:
    groups: tuple[CandidateGroup, ...]
    over_cap: int


class UsagePageTruncated(Exception):
    """A page at the smallest size reached the row limit, so the scan cannot read all of its rows."""


class JudgeUnavailable(Exception):
    """Too many judge calls failed, so the section would undercount re-derivations."""


def build_candidate_groups(queries: Iterable[AgentQuery], index: CatalogIndex) -> list[CandidateGroup]:
    occurrences: dict[tuple[UUID, str, str], list[AgentQuery]] = defaultdict(list)
    for query in queries:
        try:
            measures = extract_measures(query.sql)
        except MeasureExtractionError:
            continue
        matched = {
            match.metric_id
            for measure in measures
            if (match := index.classify(measure)).outcome != ShapeOutcome.UNCOVERED and match.metric_id is not None
        }
        sql_key = hashlib.sha256(query.sql.strip().encode()).hexdigest()
        # The judge reads one intent per group, so the same SQL asked for another question is its own group.
        intent_key = " ".join(query.intent.split()).lower()
        for metric_id in matched:
            occurrences[(metric_id, sql_key, intent_key)].append(query)

    return [
        CandidateGroup(metric_id=metric_id, sql=runs[0].sql, intent=runs[0].intent, occurrences=tuple(runs))
        for (metric_id, _, _), runs in occurrences.items()
    ]


def select_for_judging(groups: list[CandidateGroup], cap: int = JUDGE_CALL_CAP) -> JudgeSelection:
    """Pick the groups the judge reads. Groups with a non-scout run come first, then the most-run."""
    ordered = sorted(
        groups,
        key=lambda group: (group.scout_only, -len(group.occurrences), str(group.metric_id), group.sql),
    )
    return JudgeSelection(groups=tuple(ordered[:cap]), over_cap=max(0, len(ordered) - cap))


def read_metric_first(query: AgentQuery, metric_name: str, calls: Iterable[CatalogCall]) -> bool:
    """True when the agent read or ran the metric earlier in the same session, then wrote its own SQL."""
    return any(
        call.trace_id == query.trace_id
        and call.occurred_at <= query.occurred_at
        and call.tool in _DESCRIBE_TOOLS
        and call.metric_name == metric_name
        for call in calls
    )


def assemble_adjusted_runs(
    groups: Iterable[CandidateGroup],
    verdicts: Iterable[JudgeVerdict],
    metric_names: dict[UUID, str],
    calls_by_trace: dict[str, list[CatalogCall]],
) -> list[AdjustedRun]:
    matched = [
        (group, verdict, occurrence)
        for group, verdict in zip(groups, verdicts, strict=True)
        if verdict.relation != JudgeRelation.DIFFERENT
        for occurrence in group.occurrences
    ]
    # The cap applies before the runs are built, so a pair with many occurrences never copies all their text.
    if len(matched) > _MAX_STORED_RUNS:
        logger.warning("data_catalog_usage_adjusted_runs_capped", runs=len(matched), kept=_MAX_STORED_RUNS)
        matched = sorted(matched, key=lambda item: item[2].occurred_at, reverse=True)[:_MAX_STORED_RUNS]
    return [
        AdjustedRun(
            metric_id=group.metric_id,
            read_metric_first=read_metric_first(
                occurrence, metric_names[group.metric_id], calls_by_trace.get(occurrence.trace_id, [])
            ),
            relation=verdict.relation,
            intent=occurrence.intent[:_STORED_TEXT_CHARS],
            sql=occurrence.sql[:_STORED_TEXT_CHARS],
            reasoning=verdict.reasoning,
            occurred_at=occurrence.occurred_at,
            session_id=occurrence.trace_id or None,
            is_scout=occurrence.is_scout,
        )
        for group, verdict, occurrence in matched
    ]


def fetch_agent_queries(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> list[AgentQuery]:
    return [
        AgentQuery(
            occurred_at=occurred_at,
            trace_id=trace_id,
            distinct_id=distinct_id,
            intent=intent,
            sql=sql,
            is_scout=source == SCOUT_SOURCE,
        )
        for occurred_at, trace_id, distinct_id, intent, sql, source in paged_rows(
            _AGENT_SQL_QUERY, team, telemetry_team, window_start, window_end, "DataCatalogUsageAgentSQL"
        )
        if sql
    ]


def fetch_catalog_calls(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> dict[str, list[CatalogCall]]:
    calls: dict[str, list[CatalogCall]] = defaultdict(list)
    for trace_id, occurred_at, tool, metric_name in paged_rows(
        _CATALOG_CALLS_QUERY, team, telemetry_team, window_start, window_end, "DataCatalogUsageCatalogCalls"
    ):
        calls[trace_id].append(
            CatalogCall(trace_id=trace_id, occurred_at=occurred_at, tool=tool, metric_name=metric_name)
        )
    return calls


def paged_rows(
    query: str,
    team: Team,
    telemetry_team: Team,
    window_start: datetime,
    window_end: datetime,
    query_type: str,
    placeholders: dict[str, ast.Expr] | None = None,
) -> Iterator[tuple]:
    page_start = window_start
    while page_start < window_end:
        page_end = min(page_start + _PAGE, window_end)
        yield from _page_rows(query, team, telemetry_team, page_start, page_end, query_type, placeholders)
        page_start = page_end


def _page_rows(
    query: str,
    team: Team,
    telemetry_team: Team,
    page_start: datetime,
    page_end: datetime,
    query_type: str,
    placeholders: dict[str, ast.Expr] | None = None,
) -> Iterator[tuple]:
    with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
        response = execute_hogql_query(
            query=parse_select(query),
            team=telemetry_team,
            placeholders={
                "start": ast.Constant(value=page_start),
                "end": ast.Constant(value=page_end),
                "project": ast.Constant(value=str(team.uuid)),
                "row_limit": ast.Constant(value=_PAGE_ROW_LIMIT),
                **(placeholders or {}),
            },
            query_type=query_type,
            workload=Workload.OFFLINE,
            # A profile that breaks on timeout returns a partial page with no error, so the step fails instead.
            settings=HogQLGlobalSettings(timeout_overflow_mode="throw"),
        )
    rows = response.results or []
    if len(rows) < _PAGE_ROW_LIMIT:
        yield from rows
        return
    half = (page_end - page_start) / 2
    if half < _MIN_PAGE:
        raise UsagePageTruncated(
            f"{query_type} returned {len(rows)} rows for the page that starts at {page_start.isoformat()}."
        )
    middle = page_start + half
    yield from _page_rows(query, team, telemetry_team, page_start, middle, query_type, placeholders)
    yield from _page_rows(query, team, telemetry_team, middle, page_end, query_type, placeholders)


@frozen
class _DetectionPlan:
    selection: JudgeSelection
    briefs: dict[UUID, MetricBrief]
    calls_by_trace: dict[str, list[CatalogCall]]


def _plan_detection(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> _DetectionPlan:
    team = Team.objects.select_related("organization").get(id=team_id)
    # The check comes before the scans, so a team without consent costs no queries and no model calls.
    require_ai_consent(team)
    telemetry_team = Team.objects.get(id=telemetry_team_id)
    window = usage_snapshot_window(team_id, snapshot_id)
    index = CatalogIndex.for_team(team)
    briefs = _briefs(team)

    units = stored_conversations(team_id, snapshot_id)
    queries = in_conversations(
        fetch_agent_queries(team=team, telemetry_team=telemetry_team, window_start=window.start, window_end=window.end),
        units,
    )
    # A metric without a brief cannot be judged, so its groups must not take judge slots.
    groups = [group for group in build_candidate_groups(queries, index) if group.metric_id in briefs]
    selection = select_for_judging(groups)
    if selection.over_cap:
        logger.warning("data_catalog_usage_judge_cap_reached", team_id=team_id, over_cap=selection.over_cap)
    calls = calls_in_conversations(
        fetch_catalog_calls(
            team=team,
            telemetry_team=telemetry_team,
            window_start=window.start - CATALOG_CALL_LOOKBACK,
            window_end=window.end,
        ),
        units,
    )
    return _DetectionPlan(selection=selection, briefs=briefs, calls_by_trace=calls)


def _briefs(team: Team) -> dict[UUID, MetricBrief]:
    """The judge's view of each live metric. A definition that does not convert skips its metric, not the scan."""
    briefs: dict[UUID, MetricBrief] = {}
    for metric in Metric.objects.for_team(team.id).filter(deleted=False):
        try:
            briefs[metric.id] = _brief(metric, team)
        except Exception as error:
            logger.warning("data_catalog_usage_brief_failed", metric_id=str(metric.id), error=str(error))
    return briefs


def in_conversations(queries: Iterable[AgentQuery], units: dict[str, str]) -> list[AgentQuery]:
    """The queries with each session id replaced by its conversation id, so a read in an earlier piece counts."""
    return [dataclasses.replace(query, trace_id=units.get(query.trace_id, query.trace_id)) for query in queries]


def calls_in_conversations(
    calls_by_trace: dict[str, list[CatalogCall]], units: dict[str, str]
) -> dict[str, list[CatalogCall]]:
    by_unit: dict[str, list[CatalogCall]] = defaultdict(list)
    for trace_id, calls in calls_by_trace.items():
        unit = units.get(trace_id, trace_id)
        by_unit[unit].extend(dataclasses.replace(call, trace_id=unit) for call in calls)
    return {unit: sorted(calls, key=lambda call: call.occurred_at) for unit, calls in by_unit.items()}


def _brief(metric: Metric, team: Team) -> MetricBrief:
    definition = metric.definition or {}
    if definition.get("kind") == HOGQL_DEFINITION_KIND:
        text = str(definition.get("query") or "")
        # The query holds placeholders, and the values bound to them are part of what the metric measures.
        if isinstance(values := definition.get("values"), dict) and values:
            text += f"\nPlaceholder values: {json.dumps(values, sort_keys=True, default=str)}"
    else:
        text = definition_to_hogql(definition, team) or json.dumps(definition)
    return MetricBrief(name=metric.name, description=metric.description, definition=text)


async def detect_adjusted_runs_into_snapshot(
    *, team_id: int, snapshot_id: UUID, telemetry_team_id: int, heartbeat: Callable[[], None]
) -> int:
    """Judge the scan window's candidate pairs and write the snapshot's ``adjusted_runs`` section."""
    plan = await database_sync_to_async(_plan_detection, thread_sensitive=False)(
        team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=telemetry_team_id
    )
    groups = plan.selection.groups
    semaphore = asyncio.Semaphore(_JUDGE_CONCURRENCY)

    async with build_async_anthropic_client(
        product="django",
        ai_product="data_catalog_usage_judge",
        team_id=team_id,
        trace_id=f"data-catalog-usage-{snapshot_id}",
    ) as client:

        async def judge(group: CandidateGroup) -> JudgeVerdict:
            async with semaphore:
                verdict = await judge_pair(client, plan.briefs[group.metric_id], group.intent, group.sql)
            heartbeat()
            return verdict

        verdicts = await asyncio.gather(*(judge(group) for group in groups))

    failed = sum(verdict.failed for verdict in verdicts)
    if failed > len(groups) * _MAX_FAILED_SHARE:
        raise JudgeUnavailable(f"{failed} of {len(groups)} judge calls failed.")
    if failed:
        logger.warning("data_catalog_usage_judge_partial_failure", team_id=team_id, failed=failed, judged=len(groups))

    names = {metric_id: brief.name for metric_id, brief in plan.briefs.items()}
    runs = assemble_adjusted_runs(groups, verdicts, names, plan.calls_by_trace)
    await database_sync_to_async(write_payload_sections, thread_sensitive=False)(
        team_id, snapshot_id, adjusted_runs=runs
    )
    return len(runs)
