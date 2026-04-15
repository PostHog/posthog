"""HogQL data access for Stage B evaluation clustering.

Two queries:

- ``fetch_evaluation_embeddings`` — pulls accumulated eval embeddings for a job
  via ``endsWith(rendering, '_{job_id}')``, matching the Stage A rendering
  convention ``{team_id}_{run_ts}_{job_id}``.
- ``fetch_evaluation_metadata`` — joins the sampled $ai_evaluation rows to their
  target $ai_generation (via $ai_target_event_id) to surface both
  eval-specific metadata (name/result/runtime/reasoning/judge_cost) and
  generation operational metrics (cost/latency/tokens/model/error).

A LEFT JOIN is used so that a missing / purged generation degrades gracefully:
eval-only fields populate, operational fields stay None.
"""

from dataclasses import dataclass
from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.temporal.llm_analytics.evaluation_clustering.constants import LLMA_EVALUATION_DOCUMENT_TYPE

logger = structlog.get_logger(__name__)

# Matches CLUSTERING_QUERY_MAX_EXECUTION_TIME in trace_clustering/data.py — the default
# HogQL timeout is 60s, which can be tight for high-volume eval jobs.
CLUSTERING_QUERY_MAX_EXECUTION_TIME = 120


@dataclass
class EvaluationMetadata:
    """Per-evaluation metadata joined with its target generation's operational metrics."""

    eval_event_id: str  # $ai_evaluation event uuid — also the embeddings document_id
    evaluation_name: str | None
    evaluation_result: bool | None
    evaluation_applicable: bool | None
    evaluation_runtime: str | None  # "llm_judge" | "hog"
    evaluation_reasoning: str | None
    judge_cost_usd: float | None  # $ai_total_cost_usd on the eval (only populated for llm_judge)

    # Linkage — both may be None if the linked generation was retention-purged or never existed
    target_generation_id: str | None  # $ai_target_event_id
    target_trace_id: str | None  # $ai_trace_id

    # Operational metrics from the linked generation (None when the generation isn't found)
    generation_cost_usd: float | None
    generation_latency_ms: float | None
    generation_input_tokens: int | None
    generation_output_tokens: int | None
    generation_model: str | None
    generation_is_error: bool | None


def fetch_evaluation_embeddings(
    team: Team,
    job_id: str,
    max_samples: int,
) -> tuple[list[str], dict[str, list[float]]]:
    """Read up to max_samples eval embeddings accumulated by Stage A for this job.

    Stage A writes a new row every hour tagged with
    ``rendering = {team_id}_{run_ts}_{job_id}``; we match by suffix since only the
    job id is stable across runs. Random-order sampling keeps the read size bounded
    when a job has accumulated far more than ``max_samples`` over time.
    """
    query = parse_select(
        """
        SELECT toString(document_id) as eval_event_id, embedding
        FROM raw_document_embeddings
        WHERE document_type = {document_type}
            AND endsWith(rendering, {job_id_suffix})
            AND length(embedding) > 0
        ORDER BY rand()
        LIMIT {max_samples}
        """
    )

    placeholders: dict[str, ast.Expr] = {
        "document_type": ast.Constant(value=LLMA_EVALUATION_DOCUMENT_TYPE),
        "job_id_suffix": ast.Constant(value=f"_{job_id}"),
        "max_samples": ast.Constant(value=max_samples),
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="EvalEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    rows = result.results or []
    eval_ids: list[str] = []
    embeddings: dict[str, list[float]] = {}
    for row in rows:
        eval_id = row[0]
        eval_ids.append(eval_id)
        embeddings[eval_id] = row[1]

    logger.info("fetch_evaluation_embeddings_result", job_id=job_id, num_rows=len(rows), team_id=team.id)
    return eval_ids, embeddings


def fetch_evaluation_metadata(
    team: Team,
    eval_event_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, EvaluationMetadata]:
    """Join $ai_evaluation rows to their target $ai_generation and return both sides.

    Window bounds are enforced so the events table scan stays bounded. In practice
    clustering runs read embeddings that accumulated over ~24h so the caller should
    pass a window a day or two wider than the embeddings window.
    """
    if not eval_event_ids:
        return {}

    eval_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=eid) for eid in eval_event_ids])

    # Self-join events → events via $ai_target_event_id.
    # The inner query pulls the eval rows keyed by uuid; the outer LEFT JOIN brings
    # in the matching generation. HogQL team-scopes both sides automatically.
    query = parse_select(
        """
        SELECT
            toString(e.uuid) as eval_event_id,
            e.properties.$ai_evaluation_name as evaluation_name,
            e.properties.$ai_evaluation_result as evaluation_result,
            e.properties.$ai_evaluation_applicable as evaluation_applicable,
            e.properties.$ai_evaluation_runtime as evaluation_runtime,
            e.properties.$ai_evaluation_reasoning as evaluation_reasoning,
            toFloat(e.properties.$ai_total_cost_usd) as judge_cost_usd,
            e.properties.$ai_target_event_id as target_generation_id,
            e.properties.$ai_trace_id as target_trace_id,
            toFloat(g.properties.$ai_total_cost_usd) as generation_cost_usd,
            toFloat(g.properties.$ai_latency) as generation_latency,
            toInt(g.properties.$ai_input_tokens) as generation_input_tokens,
            toInt(g.properties.$ai_output_tokens) as generation_output_tokens,
            g.properties.$ai_model as generation_model,
            g.properties.$ai_is_error as generation_is_error
        FROM events AS e
        LEFT JOIN events AS g
            ON toString(g.uuid) = e.properties.$ai_target_event_id
            AND g.event = '$ai_generation'
        WHERE e.event = '$ai_evaluation'
            AND e.timestamp >= {start_dt}
            AND e.timestamp < {end_dt}
            AND toString(e.uuid) IN {eval_ids}
        LIMIT {limit}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="EvalMetadataForClustering",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "eval_ids": eval_ids_tuple,
                "limit": ast.Constant(value=len(eval_event_ids)),
            },
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    metadata: dict[str, EvaluationMetadata] = {}
    for row in result.results or []:
        eval_id = row[0]
        if not eval_id:
            continue
        metadata[eval_id] = EvaluationMetadata(
            eval_event_id=eval_id,
            evaluation_name=row[1],
            evaluation_result=_coerce_bool(row[2]),
            evaluation_applicable=_coerce_bool(row[3]),
            evaluation_runtime=row[4] or None,
            evaluation_reasoning=row[5] or None,
            judge_cost_usd=row[6],
            target_generation_id=row[7] or None,
            target_trace_id=row[8] or None,
            generation_cost_usd=row[9],
            generation_latency_ms=row[10],
            generation_input_tokens=row[11],
            generation_output_tokens=row[12],
            generation_model=row[13] or None,
            generation_is_error=_coerce_bool(row[14]),
        )

    logger.info(
        "fetch_evaluation_metadata_result",
        team_id=team.id,
        requested=len(eval_event_ids),
        returned=len(metadata),
    )
    return metadata


def _coerce_bool(value: object) -> bool | None:
    """ClickHouse JSONExtract on boolean properties returns the string `'true'`/`'false'`.

    Normalize to a Python bool for downstream metric aggregation; return None when
    the property was absent (empty string) so we can distinguish "not applicable"
    from "false".
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
    return None
