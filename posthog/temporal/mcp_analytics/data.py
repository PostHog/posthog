"""HogQL data access for MCP analytics workflows."""

from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.temporal.mcp_analytics.constants import (
    INTENT_DOCUMENT_TYPE,
    MAX_SPAN_REASONING_CHARS,
    MCP_ANALYTICS_PRODUCT,
)
from posthog.temporal.mcp_analytics.models import IntentStat

logger = structlog.get_logger(__name__)

# HogQL query budget — these run in background Temporal activities and join
# decent-sized event windows, so we lift the default 60s limit.
MCP_QUERY_MAX_EXECUTION_TIME = 120


def fetch_intent_stats(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
) -> list[IntentStat]:
    """Fetch distinct $mcp_intent values with failure / retry signal joined in.

    Only intents that drove at least one mcp_tool_call in the window are returned.
    Sample session ids are limited to 3 per intent to keep payloads small.
    """
    query = parse_select(
        """
        SELECT
            properties.$mcp_intent as intent,
            count() as total_calls,
            countIf(properties.$mcp_is_error = 'true' OR properties.$mcp_is_error = true) as error_count,
            countIf(empty(toString(properties.$mcp_response))) as empty_response_count,
            uniqExact(properties.$mcp_tool_name) as distinct_tools_attempted,
            -- ClickHouse rejects nested aggregates (`argMax(x, count())`), so use
            -- topK(1) which returns an array of the most-frequent value.
            topK(1)(properties.$mcp_tool_name)[1] as dominant_tool,
            groupArray(3)(properties.$session_id) as sample_session_ids
        FROM events
        WHERE event = 'mcp_tool_call'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND notEmpty(toString(properties.$mcp_intent))
        GROUP BY intent
        ORDER BY total_calls DESC
        LIMIT {max_samples}
        """
    )

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "max_samples": ast.Constant(value=max_samples),
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="MCPAnalyticsIntentStats",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=MCP_QUERY_MAX_EXECUTION_TIME),
        )

    stats: list[IntentStat] = []
    for row in result.results or []:
        intent = (row[0] or "").strip()
        if not intent:
            continue
        sample_sessions = [s for s in (row[6] or []) if s]
        stats.append(
            IntentStat(
                intent=intent,
                total_calls=int(row[1] or 0),
                error_count=int(row[2] or 0),
                empty_response_count=int(row[3] or 0),
                distinct_tools_attempted=int(row[4] or 0),
                dominant_tool=str(row[5] or ""),
                sample_session_ids=list(dict.fromkeys(sample_sessions))[:3],
            )
        )

    logger.info("mcp_analytics_fetch_intent_stats", num_intents=len(stats))
    return stats


def fetch_span_reasoning_snippets(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
) -> list[tuple[str, str]]:
    """Fetch MCP-origin $ai_span reasoning snippets for embedding.

    Returns (document_id, content) tuples. document_id is the underlying event uuid
    so each snippet stays addressable and we can dedupe across runs.
    """
    query = parse_select(
        """
        SELECT
            toString(uuid) as document_id,
            substring(coalesce(
                toString(properties.$ai_output_text),
                toString(properties.$ai_output),
                toString(properties.$ai_input_text),
                ''
            ), 1, {max_chars}) as content
        FROM events
        WHERE event = '$ai_span'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND properties.$ai_product = 'mcp'
            AND notEmpty(coalesce(
                toString(properties.$ai_output_text),
                toString(properties.$ai_output),
                toString(properties.$ai_input_text),
                ''
            ))
        ORDER BY timestamp DESC
        LIMIT {max_samples}
        """
    )

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "max_samples": ast.Constant(value=max_samples),
        "max_chars": ast.Constant(value=MAX_SPAN_REASONING_CHARS),
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="MCPAnalyticsSpanReasoning",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=MCP_QUERY_MAX_EXECUTION_TIME),
        )

    rows: list[tuple[str, str]] = []
    for row in result.results or []:
        doc_id = (row[0] or "").strip()
        content = (row[1] or "").strip()
        if doc_id and content:
            rows.append((doc_id, content))
    return rows


def fetch_already_embedded_document_ids(
    team: Team,
    document_type: str,
    embedding_model: str,
    since: datetime,
) -> set[str]:
    """Look up which document_ids the embedding worker has already processed.

    Used by the embedding-emit activity to skip re-emitting requests for documents
    we already have embeddings for. The lookup uses the model-specific indexed
    table via the document_embeddings lazy table.

    `since` bounds the lookup so we don't scan months of accumulated embeddings on
    every daily run — caller should pass the start of the current lookback window.
    Anything older than that is outside the workflow's working set anyway.
    """
    query = parse_select(
        """
        SELECT DISTINCT document_id
        FROM document_embeddings
        WHERE model_name = {model_name}
            AND product = {product}
            AND document_type = {document_type}
            AND timestamp >= {since}
        """
    )

    placeholders: dict[str, ast.Expr] = {
        "model_name": ast.Constant(value=embedding_model),
        "product": ast.Constant(value=MCP_ANALYTICS_PRODUCT),
        "document_type": ast.Constant(value=document_type),
        "since": ast.Constant(value=since),
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="MCPAnalyticsExistingEmbeddings",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=MCP_QUERY_MAX_EXECUTION_TIME),
        )

    return {row[0] for row in (result.results or []) if row[0]}


def fetch_intent_embeddings(
    team: Team,
    intents: list[str],
    embedding_model: str,
) -> dict[str, list[float]]:
    """Look up embeddings for a specific set of intents from the indexed table."""
    if not intents:
        return {}

    intents_tuple = ast.Tuple(exprs=[ast.Constant(value=i) for i in intents])
    query = parse_select(
        """
        SELECT document_id, embedding
        FROM document_embeddings
        WHERE model_name = {model_name}
            AND product = {product}
            AND document_type = {document_type}
            AND document_id IN {document_ids}
        """
    )

    placeholders: dict[str, ast.Expr] = {
        "model_name": ast.Constant(value=embedding_model),
        "product": ast.Constant(value=MCP_ANALYTICS_PRODUCT),
        "document_type": ast.Constant(value=INTENT_DOCUMENT_TYPE),
        "document_ids": intents_tuple,
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="MCPAnalyticsIntentEmbeddings",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=MCP_QUERY_MAX_EXECUTION_TIME),
        )

    embeddings: dict[str, list[float]] = {}
    for row in result.results or []:
        doc_id, embedding = row[0], row[1]
        if doc_id and embedding and len(embedding) > 0:
            embeddings[doc_id] = list(embedding)
    return embeddings
