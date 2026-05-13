"""On-demand query that returns candidate missing MCP tools.

Combines two signals:
1. **Intent clusters** — read from the latest `$mcp_intent_clusters` event written
   by the daily Temporal workflow. Ranked by the LLM-labeler's `gap_score`.
2. **LLM-stated gaps** — semantic search over `$ai_span` reasoning text via the
   `embedText()` HogQL function, looking for phrases like "I don't have a tool that
   does X". Ranked by cosine distance.

Both signals are computed in the same call so the frontend can render them on one
page. The intent clusters are pre-computed (daily), so reading them is cheap. The
semantic search runs at query time (~1-2 s on the indexed embedding table).
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.temporal.mcp_analytics.constants import (
    AI_SPAN_REASONING_DOCUMENT_TYPE,
    DEFAULT_EMBEDDING_MODEL,
    EVENT_NAME_INTENT_CLUSTERS,
    MCP_ANALYTICS_PRODUCT,
)

logger = structlog.get_logger(__name__)

# Probe phrases to search for in $ai_span reasoning text. The intent here is *not*
# string matching — these get embedded via embedText() and we cosine-search for
# the nearest spans, which catches paraphrases like "there isn't a tool for…".
DEFAULT_GAP_PROBE_PHRASES: list[str] = [
    "I don't have a tool that can do this",
    "There's no tool available for this",
    "I would need a tool that supports this",
    "I can't do this because no tool exists",
    "It would help if there was a tool for this",
]

# Cap distance so we don't return spans that are only weakly related.
DEFAULT_MAX_DISTANCE = 0.4
DEFAULT_RESULTS_PER_PROBE = 10
DEFAULT_QUERY_MAX_EXECUTION_TIME = 60


class IntentClusterMemberDTO(BaseModel):
    intent: str
    total_calls: int
    error_rate: float
    empty_rate: float


class IntentClusterDTO(BaseModel):
    cluster_id: int
    title: str
    description: str
    gap_score: float
    size: int
    aggregate_error_rate: float
    aggregate_empty_rate: float
    avg_distinct_tools_attempted: float
    sample_intents: list[IntentClusterMemberDTO]


class LLMStatedGapDTO(BaseModel):
    probe_phrase: str
    matched_text: str
    distance: float
    document_id: str
    timestamp: datetime | None = None


class MissingToolsCandidatesResult(BaseModel):
    clustering_run_id: str = ""
    window_start: str = ""
    window_end: str = ""
    intent_clusters: list[IntentClusterDTO] = []
    llm_stated_gaps: list[LLMStatedGapDTO] = []


@dataclass
class MissingToolsCandidatesParams:
    """Tunables for the query runner. Defaults are good for the on-demand endpoint."""

    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    probe_phrases: list[str] | None = None
    max_distance: float = DEFAULT_MAX_DISTANCE
    results_per_probe: int = DEFAULT_RESULTS_PER_PROBE
    max_intents_per_cluster: int = 5


class MissingToolsCandidatesRunner:
    """Runs the missing-tools query for a single team."""

    def __init__(self, team: Team, params: MissingToolsCandidatesParams | None = None):
        self.team = team
        self.params = params or MissingToolsCandidatesParams()

    def run(self) -> MissingToolsCandidatesResult:
        clusters_payload = self._read_latest_clusters_event()
        intent_clusters: list[IntentClusterDTO] = []
        clustering_run_id = ""
        window_start = ""
        window_end = ""

        if clusters_payload:
            clustering_run_id = clusters_payload.get("$mcp_clustering_run_id", "")
            window_start = clusters_payload.get("$mcp_window_start", "")
            window_end = clusters_payload.get("$mcp_window_end", "")
            for raw_cluster in clusters_payload.get("$mcp_clusters", []):
                intent_clusters.append(self._cluster_payload_to_dto(raw_cluster))

        # The semantic search calls embedText() which depends on the embedding worker
        # HTTP API; if it's unavailable we still want to return the pre-computed
        # intent clusters rather than 500-ing the whole endpoint.
        llm_stated_gaps: list[LLMStatedGapDTO] = []
        try:
            llm_stated_gaps = self._search_llm_stated_gaps()
        except Exception:
            logger.warning(
                "mcp_analytics_llm_stated_gap_search_failed",
                team_id=self.team.pk,
                exc_info=True,
            )

        return MissingToolsCandidatesResult(
            clustering_run_id=clustering_run_id,
            window_start=window_start,
            window_end=window_end,
            intent_clusters=intent_clusters,
            llm_stated_gaps=llm_stated_gaps,
        )

    def _read_latest_clusters_event(self) -> dict[str, Any] | None:
        query = parse_select(
            """
            SELECT
                JSONExtractString(properties, '$mcp_clustering_run_id') as clustering_run_id,
                JSONExtractString(properties, '$mcp_window_start') as window_start,
                JSONExtractString(properties, '$mcp_window_end') as window_end,
                JSONExtractRaw(properties, '$mcp_clusters') as clusters_json
            FROM events
            WHERE event = {event_name}
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
            result = execute_hogql_query(
                query_type="MCPAnalyticsLatestIntentClusters",
                query=query,
                placeholders={"event_name": ast.Constant(value=EVENT_NAME_INTENT_CLUSTERS)},
                team=self.team,
                settings=HogQLGlobalSettings(max_execution_time=DEFAULT_QUERY_MAX_EXECUTION_TIME),
            )
        rows = result.results or []
        if not rows:
            return None
        clustering_run_id, window_start, window_end, clusters_json = rows[0]
        clusters: list[Any] = []
        if clusters_json:
            try:
                parsed = json.loads(clusters_json)
                if isinstance(parsed, list):
                    clusters = parsed
            except (ValueError, TypeError):
                logger.warning("mcp_analytics_failed_to_parse_clusters_json", run_id=clustering_run_id)
        return {
            "$mcp_clustering_run_id": clustering_run_id or "",
            "$mcp_window_start": window_start or "",
            "$mcp_window_end": window_end or "",
            "$mcp_clusters": clusters,
        }

    def _cluster_payload_to_dto(self, raw: dict[str, Any]) -> IntentClusterDTO:
        members = raw.get("members", []) or []
        sample_members: list[IntentClusterMemberDTO] = []
        for m in members[: self.params.max_intents_per_cluster]:
            stat = m.get("stat", {}) or {}
            total_calls = int(stat.get("total_calls", 0) or 0)
            error_count = int(stat.get("error_count", 0) or 0)
            empty_count = int(stat.get("empty_response_count", 0) or 0)
            sample_members.append(
                IntentClusterMemberDTO(
                    intent=stat.get("intent", "") or m.get("intent", ""),
                    total_calls=total_calls,
                    error_rate=(error_count / total_calls) if total_calls else 0.0,
                    empty_rate=(empty_count / total_calls) if total_calls else 0.0,
                )
            )
        return IntentClusterDTO(
            cluster_id=int(raw.get("cluster_id", 0) or 0),
            title=raw.get("title", "") or "",
            description=raw.get("description", "") or "",
            gap_score=float(raw.get("gap_score", 0.0) or 0.0),
            size=int(raw.get("size", len(members)) or 0),
            aggregate_error_rate=float(raw.get("aggregate_error_rate", 0.0) or 0.0),
            aggregate_empty_rate=float(raw.get("aggregate_empty_rate", 0.0) or 0.0),
            avg_distinct_tools_attempted=float(raw.get("avg_distinct_tools_attempted", 0.0) or 0.0),
            sample_intents=sample_members,
        )

    def _search_llm_stated_gaps(self) -> list[LLMStatedGapDTO]:
        # `is None` rather than `or` so callers can opt out by passing []. Falling
        # through to DEFAULT_GAP_PROBE_PHRASES on `[]` was a footgun: every test
        # that thought it was disabling the semantic search was actually still
        # hitting the embedding worker.
        probes = DEFAULT_GAP_PROBE_PHRASES if self.params.probe_phrases is None else self.params.probe_phrases
        if not probes:
            return []
        # Probes are independent network round-trips (embedText + ClickHouse). Fan
        # them out so endpoint latency is bounded by the slowest single probe rather
        # than the sum across all probes.
        results: list[LLMStatedGapDTO] = []
        with ThreadPoolExecutor(max_workers=min(len(probes), 5)) as executor:
            for rows in executor.map(self._search_one_probe, probes):
                results.extend(rows)
        # Deduplicate by document_id, keep the closest match across probes
        deduped: dict[str, LLMStatedGapDTO] = {}
        for r in results:
            existing = deduped.get(r.document_id)
            if existing is None or r.distance < existing.distance:
                deduped[r.document_id] = r
        ordered = sorted(deduped.values(), key=lambda r: r.distance)
        return ordered[: self.params.results_per_probe * len(probes)]

    def _search_one_probe(self, probe: str) -> list[LLMStatedGapDTO]:
        # Note: we do not filter by team_id here — HogQL injects it automatically
        # for every query against ClickHouse tables, including document_embeddings.
        query = parse_select(
            """
            SELECT
                document_id,
                content,
                timestamp,
                cosineDistance(embedding, embedText({probe}, {model_name})) AS distance
            FROM document_embeddings
            WHERE model_name = {model_name}
                AND product = {product}
                AND document_type = {document_type}
            ORDER BY distance ASC
            LIMIT {limit}
            """
        )
        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
            result = execute_hogql_query(
                query_type="MCPAnalyticsLLMStatedGapSearch",
                query=query,
                placeholders={
                    "probe": ast.Constant(value=probe),
                    "model_name": ast.Constant(value=self.params.embedding_model),
                    "product": ast.Constant(value=MCP_ANALYTICS_PRODUCT),
                    "document_type": ast.Constant(value=AI_SPAN_REASONING_DOCUMENT_TYPE),
                    "limit": ast.Constant(value=self.params.results_per_probe),
                },
                team=self.team,
                settings=HogQLGlobalSettings(max_execution_time=DEFAULT_QUERY_MAX_EXECUTION_TIME),
            )
        rows: list[LLMStatedGapDTO] = []
        for row in result.results or []:
            doc_id, content, ts, distance = row[0], row[1], row[2], row[3]
            if not doc_id or distance is None or distance > self.params.max_distance:
                continue
            rows.append(
                LLMStatedGapDTO(
                    probe_phrase=probe,
                    matched_text=(content or "")[:500],
                    distance=float(distance),
                    document_id=str(doc_id),
                    timestamp=ts if isinstance(ts, datetime) else None,
                )
            )
        return rows
