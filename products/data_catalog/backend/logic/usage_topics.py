"""Group a team's agent sessions into topics, with how each topic got its numbers.

A topic is an open cluster of session intents, not a fixed taxonomy. Scout and setup-wizard
sessions stay out, because topics describe what people ask; the run counts count scouts apart.
"""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.mcp_analytics.backend.facade.api import cluster_texts

from ..facade.contracts import TopicCluster, TopicCoverage
from ..facade.enums import FetchOutcome
from .usage_snapshots import read_payload, usage_snapshot_window, write_payload_sections

logger = structlog.get_logger(__name__)

LABEL_MODEL = "claude-haiku-4-5"
MAX_TOPICS = 30

_SAMPLE_INTENTS = 3
_LABEL_CONCURRENCY = 8
_MAX_TITLE_CHARS = 80
_RUN_TOOL = "data-catalog-metric-run"
_SQL_TOOL = "execute-sql"
# A session that called none of these tools computed no number, so it says nothing about catalog coverage.
_DATA_TOOLS = (_RUN_TOOL, _SQL_TOOL, "insight-query", "dashboard-insights-run")
_DATA_TOOL_PREFIX = "query-"

# Clustering is quadratic in memory, so the scan clusters a hash sample of 1000 sessions. Ordering by
# the session hash keeps the sample stable between scans and unbiased across sources. The sample takes
# only sessions that queried data, so sessions that only read tickets or docs do not fill it.
_SESSIONS_QUERY = """
SELECT session, intent, tools
FROM (
    SELECT
        toString(properties.$session_id) AS session,
        argMaxIf(toString(properties.$mcp_intent), timestamp, length(toString(properties.$mcp_intent)) > 0) AS intent,
        groupUniqArray(toString(properties.$mcp_tool_name)) AS tools,
        max(toString(properties.source) IN ('self_driving', 'wizard')) AS excluded,
        max(toString(properties.$mcp_tool_name) IN {data_tools} OR startsWith(toString(properties.$mcp_tool_name), {data_tool_prefix})) AS queried
    FROM events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= {start}
        AND timestamp < {end}
        AND toString(properties.$mcp_project_id) = {project}
        AND length(toString(properties.$session_id)) > 0
    GROUP BY session
)
WHERE excluded = 0 AND queried = 1 AND length(intent) > 0
ORDER BY cityHash64(session)
LIMIT 1000
"""

_LABEL_PROMPT = """These are questions people asked an AI agent about their product data:

{intents}

Name the topic they share in 3 to 6 words, in sentence case. Reply with the name only."""


@frozen
class SessionText:
    session_id: str
    intent: str
    tools: frozenset[str]


@frozen
class _TopicDraft:
    session_count: int
    coverage: TopicCoverage
    sample_intents: tuple[str, ...]


def session_coverage(session: SessionText, outcomes: set[FetchOutcome]) -> str:
    """The best way the session reached a number. A canonical run beats any re-derivation."""
    if _RUN_TOOL in session.tools:
        return "canonical"
    if FetchOutcome.ADAPTED in outcomes:
        return "adapted"
    if outcomes:
        return "silent"
    if _SQL_TOOL in session.tools:
        return "raw_sql_only"
    return "no_sql"


def build_topic_drafts(
    sessions: list[SessionText], labels: list[int | None], outcomes_by_session: dict[str, set[FetchOutcome]]
) -> list[_TopicDraft]:
    members: dict[int, list[SessionText]] = defaultdict(list)
    for session, label in zip(sessions, labels, strict=True):
        if label is not None:
            members[label].append(session)

    drafts = []
    for cluster in members.values():
        coverage = Counter(
            session_coverage(session, outcomes_by_session.get(session.session_id, set())) for session in cluster
        )
        drafts.append(
            _TopicDraft(
                session_count=len(cluster),
                coverage=TopicCoverage(
                    canonical=coverage["canonical"],
                    adapted=coverage["adapted"],
                    silent=coverage["silent"],
                    raw_sql_only=coverage["raw_sql_only"],
                    no_sql=coverage["no_sql"],
                ),
                sample_intents=tuple(dict.fromkeys(session.intent for session in cluster))[:_SAMPLE_INTENTS],
            )
        )
    drafts.sort(key=lambda draft: (-draft.session_count, draft.sample_intents))
    return drafts[:MAX_TOPICS]


def fetch_topic_sessions(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> list[SessionText]:
    with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
        response = execute_hogql_query(
            query=parse_select(_SESSIONS_QUERY),
            team=telemetry_team,
            placeholders={
                "start": ast.Constant(value=window_start),
                "end": ast.Constant(value=window_end),
                "project": ast.Constant(value=str(team.id)),
                "data_tools": ast.Tuple(exprs=[ast.Constant(value=tool) for tool in _DATA_TOOLS]),
                "data_tool_prefix": ast.Constant(value=_DATA_TOOL_PREFIX),
            },
            query_type="DataCatalogUsageTopicSessions",
            workload=Workload.OFFLINE,
        )
    return [
        SessionText(session_id=session, intent=intent, tools=frozenset(tools))
        for session, intent, tools in response.results or []
    ]


async def label_topic(client: AsyncAnthropic, intents: tuple[str, ...]) -> str:
    """A short topic name, or the first intent when the call fails."""
    fallback = intents[0][:_MAX_TITLE_CHARS] if intents else "Unnamed topic"
    try:
        response = await client.messages.create(
            model=LABEL_MODEL,
            messages=[{"role": "user", "content": _LABEL_PROMPT.format(intents="\n".join(f"- {i}" for i in intents))}],
            max_tokens=64,
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return text[:_MAX_TITLE_CHARS] or fallback
    except Exception as error:
        logger.warning("data_catalog_usage_topic_label_failed", error=str(error))
        return fallback


@frozen
class _TopicInputs:
    team: Team
    sessions: list[SessionText]
    outcomes_by_session: dict[str, set[FetchOutcome]]


def _load_topic_inputs(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> _TopicInputs:
    team = Team.objects.get(id=team_id)
    telemetry_team = Team.objects.get(id=telemetry_team_id)
    window = usage_snapshot_window(team_id, snapshot_id)
    sessions = fetch_topic_sessions(
        team=team, telemetry_team=telemetry_team, window_start=window.start, window_end=window.end
    )

    # The adjusted-runs step runs first, so its section says which sessions re-derived a metric.
    payload = read_payload(team_id, snapshot_id)
    outcomes: dict[str, set[FetchOutcome]] = defaultdict(set)
    for run in payload.adjusted_runs or []:
        if run.session_id and not run.is_scout:
            outcomes[run.session_id].add(run.fetch_outcome)
    return _TopicInputs(team=team, sessions=sessions, outcomes_by_session=dict(outcomes))


async def collect_topics_into_snapshot(
    *, team_id: int, snapshot_id: UUID, telemetry_team_id: int, heartbeat: Callable[[], None]
) -> int:
    """Cluster the window's agent sessions into topics and write the snapshot's ``topics`` section."""
    inputs = await database_sync_to_async(_load_topic_inputs, thread_sensitive=False)(
        team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=telemetry_team_id
    )
    labels = await cluster_texts(inputs.team, [session.intent for session in inputs.sessions])
    heartbeat()
    drafts = build_topic_drafts(inputs.sessions, labels, inputs.outcomes_by_session)

    semaphore = asyncio.Semaphore(_LABEL_CONCURRENCY)
    async with build_async_anthropic_client(
        product="django",
        ai_product="data_catalog_usage_topics",
        team_id=team_id,
        trace_id=f"data-catalog-usage-{snapshot_id}",
    ) as client:

        async def title(draft: _TopicDraft) -> str:
            async with semaphore:
                return await label_topic(client, draft.sample_intents)

        titles = await asyncio.gather(*(title(draft) for draft in drafts))

    topics = [
        TopicCluster(
            title=topic_title,
            session_count=draft.session_count,
            coverage=draft.coverage,
            sample_intents=list(draft.sample_intents),
        )
        for draft, topic_title in zip(drafts, titles, strict=True)
    ]
    await database_sync_to_async(write_payload_sections, thread_sensitive=False)(team_id, snapshot_id, topics=topics)
    return len(topics)
