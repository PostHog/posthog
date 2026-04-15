"""Stage A — per-job sample $ai_evaluation events, compose text, enqueue embeddings."""

from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog
from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.evaluation_clustering.constants import LLMA_EVALUATION_DOCUMENT_TYPE
from posthog.temporal.llm_analytics.evaluation_clustering.models import SamplerActivityInputs, SamplerActivityResult

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_PRODUCT
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


def _compose_evaluation_text(
    name: str | None,
    result: Any,
    applicable: Any,
    reasoning: str | None,
) -> str:
    """Build the short text representation embedded for one $ai_evaluation event.

    Format intentionally compact so embeddings pick up on evaluator + verdict + reasoning
    without being dominated by boilerplate.
    """
    verdict: str
    # $ai_evaluation_applicable is only set when the evaluation allows N/A. When it's
    # present and false, the evaluator decided the criteria didn't apply — surface that
    # instead of the pass/fail boolean.
    if applicable is False or (isinstance(applicable, str) and applicable.lower() == "false"):
        verdict = "n/a"
    elif result is True or (isinstance(result, str) and result.lower() == "true"):
        verdict = "pass"
    elif result is False or (isinstance(result, str) and result.lower() == "false"):
        verdict = "fail"
    else:
        verdict = "unknown"

    return f"Evaluation: {name or 'unknown'}\nVerdict: {verdict}\nReasoning: {reasoning or ''}"


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 string with optional trailing Z into a datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _sample_and_embed_sync(inputs: SamplerActivityInputs) -> SamplerActivityResult:
    try:
        team = Team.objects.get(id=inputs.team_id)
    except Team.DoesNotExist:
        logger.info("Team not found, skipping eval sampler run", team_id=inputs.team_id, job_id=inputs.job_id)
        return SamplerActivityResult(team_id=inputs.team_id, job_id=inputs.job_id, sampled=0, embedded=0)

    window_start = _parse_iso(inputs.window_start)
    window_end = _parse_iso(inputs.window_end)

    # Translate the user-supplied property filters into a HogQL expression.
    # Eval jobs typically filter by $ai_evaluation_name or $ai_evaluation_runtime
    # to scope clustering to one evaluator; callers may also provide no filters at all.
    filter_expr: ast.Expr | None = None
    if inputs.event_filters:
        filter_exprs = [property_to_expr(f, team) for f in inputs.event_filters]
        filter_expr = ast.And(exprs=filter_exprs) if len(filter_exprs) > 1 else filter_exprs[0]

    query = parse_select(
        """
        SELECT
            toString(uuid) as event_uuid,
            properties.$ai_evaluation_name as eval_name,
            properties.$ai_evaluation_result as eval_result,
            properties.$ai_evaluation_applicable as eval_applicable,
            properties.$ai_evaluation_reasoning as eval_reasoning
        FROM events
        WHERE event = '$ai_evaluation'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND countIf({filter_expr}) > 0
        ORDER BY rand()
        LIMIT {max_samples}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="EvalSamplingForClustering",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "filter_expr": filter_expr or ast.Constant(value=True),
                "max_samples": ast.Constant(value=inputs.max_samples),
            },
            team=team,
            limit_context=LimitContext.QUERY_ASYNC,
        )

    rows = result.results or []
    if not rows:
        logger.info(
            "eval_sampler_no_rows",
            team_id=team.id,
            job_id=inputs.job_id,
            window_start=inputs.window_start,
            window_end=inputs.window_end,
        )
        return SamplerActivityResult(team_id=team.id, job_id=inputs.job_id, sampled=0, embedded=0)

    # Keep the rendering format identical to trace/generation clustering so Stage B can
    # read eval embeddings with the same endsWith(rendering, '_{job_id}') pattern.
    rendering = f"{team.id}_{inputs.run_ts}_{inputs.job_id}"
    embedder = LLMTracesSummarizerEmbedder(team=team)

    embedded = 0
    for row in rows:
        event_uuid = row[0]
        content = _compose_evaluation_text(
            name=row[1],
            result=row[2],
            applicable=row[3],
            reasoning=row[4],
        )
        # Use the eval event UUID as document_id so repeated runs over the same window
        # would land the same row (idempotent at the document level). A collision is fine —
        # ClickHouse will just see the same (team_id, product, document_type, document_id)
        # tuple with a new timestamp/rendering.
        embedder._embed_document(
            content=content,
            document_id=event_uuid or str(uuid4()),
            document_type=LLMA_EVALUATION_DOCUMENT_TYPE,
            rendering=rendering,
            product=LLM_TRACES_SUMMARIES_PRODUCT,
        )
        embedded += 1

    logger.info(
        "eval_sampler_embedded",
        team_id=team.id,
        job_id=inputs.job_id,
        sampled=len(rows),
        embedded=embedded,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
    )

    return SamplerActivityResult(
        team_id=team.id,
        job_id=inputs.job_id,
        sampled=len(rows),
        embedded=embedded,
    )


@activity.defn
async def sample_and_embed_for_job_activity(inputs: SamplerActivityInputs) -> SamplerActivityResult:
    """Sample up to N $ai_evaluation events from a window, compose text, enqueue embeddings.

    Runs hourly per active evaluation ClusteringJob. Pure function of the inputs —
    no dedupe state, no watermark.
    """
    async with Heartbeater():
        return await database_sync_to_async(_sample_and_embed_sync, thread_sensitive=False)(inputs)
