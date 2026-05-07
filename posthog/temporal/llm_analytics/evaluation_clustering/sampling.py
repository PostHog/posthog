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
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    LLMA_EVALUATION_DOCUMENT_TYPE,
    LLMA_EVALUATION_EMBEDDING_MODEL,
)
from posthog.temporal.llm_analytics.evaluation_clustering.models import SamplerActivityInputs, SamplerActivityResult

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_PRODUCT
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


def _compose_evaluation_text(
    name: str | None,
    result: Any,
    applicable: Any,
    reasoning: str | None,
    description: str | None = None,
) -> str:
    """Build the short text representation embedded for one $ai_evaluation event.

    Format intentionally compact so embeddings pick up on evaluator + verdict + reasoning
    without being dominated by boilerplate. The optional evaluator ``description`` comes
    from the ``Evaluation`` model (not the event) — including it helps the embedding
    capture intent/rubric, not just the emitted reasoning, which is especially useful
    for short Hog-runtime reasoning like ``"OK"`` or ``"Total tokens 17250 exceeds 4000"``.
    The ``Description:`` line is omitted when empty so blank descriptions don't inject
    boilerplate that flattens the embedding space.
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

    lines = [f"Evaluation: {name or 'unknown'}"]
    if description:
        lines.append(f"Description: {description}")
    lines.append(f"Verdict: {verdict}")
    lines.append(f"Reasoning: {reasoning or ''}")
    return "\n".join(lines)


def _fetch_evaluation_descriptions(team_id: int, evaluation_ids: list[str]) -> dict[str, str]:
    """Batch-fetch Evaluation.description for the evaluators we sampled.

    One Django query per sampler run keyed by the handful of distinct evaluator ids
    in the sample — much cheaper than joining per-row. Missing or empty descriptions
    are silently skipped by the caller (``_compose_evaluation_text`` omits the line).
    """
    # Local import: the activity's top-level import graph stays free of Django model modules
    # so workflow-side imports don't accidentally pull them in via Temporal's sandbox.
    from products.llm_analytics.backend.models.evaluations import Evaluation

    # IDs come off ``$ai_evaluation_id`` as strings; filter out empty/unknown so we
    # don't ship a huge empty-id set to Postgres.
    ids = {eid for eid in evaluation_ids if eid}
    if not ids:
        return {}

    rows = Evaluation.objects.filter(team_id=team_id, id__in=ids).values_list("id", "description")
    return {str(eid): description for eid, description in rows if description}


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 string with a trailing ``Z`` into a datetime.

    Contract: only ``Z``-suffixed UTC strings produced by ``LLMAEvaluationSamplerWorkflow``
    are supported — no other offset forms or bare naïve strings. Generalise only if a
    caller needs it.
    """
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
            properties.$ai_evaluation_reasoning as eval_reasoning,
            properties.$ai_evaluation_id as eval_id
        FROM events
        WHERE event = '$ai_evaluation'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND {filter_expr}
        -- perf: ORDER BY rand() is a full scan with a per-row random key;
        -- fine at today's 250 samples/hr/job, but revisit before a high-volume
        -- tenant opts in (consider reservoir sampling or bloom-pruned windows).
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
    # Use the small (1536-dim) model — see LLMA_EVALUATION_EMBEDDING_MODEL in constants.py.
    # The lazy import keeps EmbeddingModelName out of the module top-level (avoids pulling
    # posthog.schema into the workflow-side graph via the activity module).
    from posthog.schema import EmbeddingModelName

    embedder = LLMTracesSummarizerEmbedder(
        team=team,
        embedding_model_name=EmbeddingModelName(LLMA_EVALUATION_EMBEDDING_MODEL),
    )

    # Enrich the composed text with each evaluator's description (from the Evaluation
    # model) so the embedding picks up on rubric/intent, not just the emitted reasoning.
    # Batched to a single Django query per run on the unique evaluator ids we sampled.
    descriptions_by_id = _fetch_evaluation_descriptions(
        team_id=team.id,
        evaluation_ids=[row[5] for row in rows if row[5]],
    )

    embedded = 0
    for row in rows:
        event_uuid = row[0]
        eval_id = row[5]
        content = _compose_evaluation_text(
            name=row[1],
            result=row[2],
            applicable=row[3],
            reasoning=row[4],
            description=descriptions_by_id.get(eval_id),
        )
        # Use the eval event UUID as document_id so repeated runs over the same window
        # would land the same row (idempotent at the document level). A collision is fine —
        # ClickHouse will just see the same (team_id, product, document_type, document_id)
        # tuple with a new timestamp/rendering.
        embedder.embed_document(
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

    Exceptions are stringified before propagating so Temporal's failure serializer
    doesn't trip on cyclic references inside HogQL AST nodes (query objects hold
    back-references to their parents) or ClickHouse driver exception payloads
    (context pointers into the live connection). ``ValueError`` and ``TypeError``
    are re-raised unchanged so they still match the non-retryable list in
    ``SAMPLER_ACTIVITY_RETRY_POLICY`` — those never carry cyclic references and
    must fail fast.

    ``from None`` intentionally drops the cause chain for the same serializer
    reason; the original traceback is preserved in the structured log via
    ``logger.exception`` above, which is where debugging should start.
    """
    async with Heartbeater():
        try:
            return await database_sync_to_async(_sample_and_embed_sync, thread_sensitive=False)(inputs)
        except (ValueError, TypeError):
            raise
        except Exception as exc:
            logger.exception(
                "eval_sampler_activity_failed",
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                error_type=type(exc).__name__,
            )
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from None
