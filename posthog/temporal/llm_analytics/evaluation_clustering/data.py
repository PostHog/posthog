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
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    LLMA_EVALUATION_DOCUMENT_TYPE,
    LLMA_EVALUATION_EMBEDDING_MODEL,
)

logger = structlog.get_logger(__name__)

# Matches CLUSTERING_QUERY_MAX_EXECUTION_TIME in trace_clustering/data.py — the default
# HogQL timeout is 60s, which can be tight for high-volume eval jobs.
CLUSTERING_QUERY_MAX_EXECUTION_TIME = 120


@dataclass
class EvaluationMetadata:
    """Per-evaluation metadata joined with its target generation's operational metrics."""

    eval_event_id: str  # $ai_evaluation event uuid — also the embeddings document_id
    evaluation_id: str | None  # $ai_evaluation_id — links to the Evaluation model row
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
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> tuple[list[str], dict[str, list[float]]]:
    """Read up to max_samples eval embeddings accumulated by Stage A for this job.

    Stage A writes a new row every hour tagged with
    ``rendering = {team_id}_{run_ts}_{job_id}``; we match by suffix since only the
    job id is stable across runs. Random-order sampling keeps the read size bounded
    when a job has accumulated far more than ``max_samples`` over time.

    ``window_start``/``window_end`` must align with the Stage B metadata lookup
    window — otherwise the random sample can return older eval ids that the
    downstream metadata query can't resolve (linked generations fall outside
    its window), producing clusters with missing trace/generation links.
    Passing bounds also lets ClickHouse prune date partitions on the
    ``(team_id, toDate(timestamp))`` index. Optional only to keep ad-hoc
    scripts and tests working.
    """
    # Filter by model_name so raw_document_embeddings routes to the small (1536-dim)
    # subtable in the union view, matching what Stage A wrote.
    has_window = window_start is not None and window_end is not None
    if has_window:
        query = parse_select(
            """
            SELECT toString(document_id) as eval_event_id, embedding
            FROM raw_document_embeddings
            WHERE document_type = {document_type}
                AND model_name = {model_name}
                AND endsWith(rendering, {job_id_suffix})
                AND length(embedding) > 0
                AND timestamp >= {start_dt}
                AND timestamp < {end_dt}
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
    else:
        query = parse_select(
            """
            SELECT toString(document_id) as eval_event_id, embedding
            FROM raw_document_embeddings
            WHERE document_type = {document_type}
                AND model_name = {model_name}
                AND endsWith(rendering, {job_id_suffix})
                AND length(embedding) > 0
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )

    placeholders: dict[str, ast.Expr] = {
        "document_type": ast.Constant(value=LLMA_EVALUATION_DOCUMENT_TYPE),
        "model_name": ast.Constant(value=LLMA_EVALUATION_EMBEDDING_MODEL),
        "job_id_suffix": ast.Constant(value=f"_{job_id}"),
        "max_samples": ast.Constant(value=max_samples),
    }
    if has_window:
        placeholders["start_dt"] = ast.Constant(value=window_start)
        placeholders["end_dt"] = ast.Constant(value=window_end)

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
    """Fetch eval + linked generation metadata via two queries joined in Python.

    Previously this was a single HogQL query with ``LEFT JOIN events AS g ON ...``.
    ClickHouse 26.3's join analyzer rejects the resulting ON expression because
    HogQL rewrites ``=`` as ``ifNull(equals(a, b), isNull(a) AND isNull(b))`` for
    NULL-safety, and the analyzer only accepts plain equi-join keys.

    Two sequential queries are cheap here: each side is capped by the Stage B
    embedding read cap (``CLUSTERING_MAX_SAMPLES = 1500``), and the Python-side
    dict join is O(n). Trades one extra CH round-trip per clustering run for
    clarity + portability across CH versions.

    Window bounds are enforced so the events table scan stays bounded. In practice
    clustering runs read embeddings that accumulated over ~24h so the caller should
    pass a window a day or two wider than the embeddings window.
    """
    if not eval_event_ids:
        return {}

    eval_rows = _fetch_evaluation_rows(team, eval_event_ids, window_start, window_end)
    if not eval_rows:
        return {}

    # Collect target generation ids so we can batch-fetch them in one query.
    target_generation_ids = sorted({row["target_generation_id"] for row in eval_rows if row["target_generation_id"]})
    generations = _fetch_linked_generations(team, target_generation_ids, window_start, window_end)

    metadata: dict[str, EvaluationMetadata] = {}
    for row in eval_rows:
        target_id = row["target_generation_id"]
        gen = generations.get(target_id) if target_id else None
        metadata[row["eval_event_id"]] = EvaluationMetadata(
            eval_event_id=row["eval_event_id"],
            evaluation_id=row["evaluation_id"] or None,
            evaluation_name=row["evaluation_name"],
            evaluation_result=_coerce_bool(row["evaluation_result"]),
            evaluation_applicable=_coerce_bool(row["evaluation_applicable"]),
            evaluation_runtime=row["evaluation_runtime"] or None,
            evaluation_reasoning=row["evaluation_reasoning"] or None,
            judge_cost_usd=row["judge_cost_usd"],
            target_generation_id=target_id or None,
            target_trace_id=row["target_trace_id"] or None,
            generation_cost_usd=gen["cost_usd"] if gen else None,
            generation_latency_ms=gen["latency_ms"] if gen else None,
            generation_input_tokens=gen["input_tokens"] if gen else None,
            generation_output_tokens=gen["output_tokens"] if gen else None,
            generation_model=(gen["model"] if gen else None) or None,
            generation_is_error=_coerce_bool(gen["is_error"]) if gen else None,
        )

    logger.info(
        "fetch_evaluation_metadata_result",
        team_id=team.id,
        requested=len(eval_event_ids),
        returned=len(metadata),
    )
    return metadata


def _fetch_evaluation_rows(
    team: Team,
    eval_event_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Pull the eval side of the join: eval-specific fields + target_generation_id."""
    eval_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=eid) for eid in eval_event_ids])

    query = parse_select(
        """
        SELECT
            toString(uuid) as eval_event_id,
            properties.$ai_evaluation_id as evaluation_id,
            properties.$ai_evaluation_name as evaluation_name,
            properties.$ai_evaluation_result as evaluation_result,
            properties.$ai_evaluation_applicable as evaluation_applicable,
            properties.$ai_evaluation_runtime as evaluation_runtime,
            properties.$ai_evaluation_reasoning as evaluation_reasoning,
            toFloat(properties.$ai_total_cost_usd) as judge_cost_usd,
            properties.$ai_target_event_id as target_generation_id,
            properties.$ai_trace_id as target_trace_id
        FROM events
        WHERE event = '$ai_evaluation'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND toString(uuid) IN {eval_ids}
        LIMIT {limit}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="EvalRowsForClustering",
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

    return [
        {
            "eval_event_id": row[0],
            "evaluation_id": row[1],
            "evaluation_name": row[2],
            "evaluation_result": row[3],
            "evaluation_applicable": row[4],
            "evaluation_runtime": row[5],
            "evaluation_reasoning": row[6],
            "judge_cost_usd": row[7],
            "target_generation_id": row[8],
            "target_trace_id": row[9],
        }
        for row in (result.results or [])
        if row[0]
    ]


def _fetch_linked_generations(
    team: Team,
    generation_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, dict]:
    """Fetch linked $ai_generation operational metrics keyed by uuid-as-string.

    Returns an empty dict when there are no ids to look up — Python-side callers
    then drop to None operational fields for every eval, matching the spec's
    "missing generation degrades gracefully" behavior.
    """
    if not generation_ids:
        return {}

    ids_tuple = ast.Tuple(exprs=[ast.Constant(value=gid) for gid in generation_ids])

    query = parse_select(
        """
        SELECT
            toString(uuid) as generation_id,
            toFloat(properties.$ai_total_cost_usd) as cost_usd,
            toFloat(properties.$ai_latency) as latency_ms,
            toInt(properties.$ai_input_tokens) as input_tokens,
            toInt(properties.$ai_output_tokens) as output_tokens,
            properties.$ai_model as model,
            properties.$ai_is_error as is_error
        FROM events
        WHERE event = '$ai_generation'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND toString(uuid) IN {ids}
        LIMIT {limit}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="GenerationsLinkedToEvals",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "ids": ids_tuple,
                "limit": ast.Constant(value=len(generation_ids)),
            },
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    return {
        row[0]: {
            "cost_usd": row[1],
            "latency_ms": row[2],
            "input_tokens": row[3],
            "output_tokens": row[4],
            "model": row[5],
            "is_error": row[6],
        }
        for row in (result.results or [])
        if row[0]
    }


def fetch_generation_contents(
    team: Team,
    generation_ids: list[str],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    max_input_chars: int = 1500,
    max_output_chars: int = 1500,
) -> dict[str, dict]:
    """Fetch the input/output text of linked $ai_generation events.

    Used by the labeling agent's ``get_generation_details`` tool — when it wants to
    ground a cluster label by examining the actual prompts/outputs that the
    evaluator reacted to, not just the evaluator's reasoning.

    Each side is truncated to bound token cost; the labeling agent rarely needs
    full transcripts and the clusters that matter are identified by *patterns*
    across many members, not by deep reading of any one.

    ``window_start``/``window_end`` are optional but recommended — without them
    ClickHouse can't prune date partitions from the ``(team_id, toDate(timestamp))``
    index and the query does a full-team scan for a handful of UUIDs. The
    labeling agent passes the same metadata lookup window the workflow uses.
    """
    if not generation_ids:
        return {}

    ids_tuple = ast.Tuple(exprs=[ast.Constant(value=gid) for gid in generation_ids])
    has_window = window_start is not None and window_end is not None
    if has_window:
        query = parse_select(
            """
            SELECT
                toString(uuid) as generation_id,
                properties.$ai_model as model,
                properties.$ai_input as input_raw,
                properties.$ai_output_choices as output_raw
            FROM events
            WHERE event = '$ai_generation'
                AND timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND toString(uuid) IN {ids}
            LIMIT {limit}
            """
        )
    else:
        query = parse_select(
            """
            SELECT
                toString(uuid) as generation_id,
                properties.$ai_model as model,
                properties.$ai_input as input_raw,
                properties.$ai_output_choices as output_raw
            FROM events
            WHERE event = '$ai_generation'
                AND toString(uuid) IN {ids}
            LIMIT {limit}
            """
        )

    placeholders: dict[str, ast.Expr] = {
        "ids": ids_tuple,
        "limit": ast.Constant(value=len(generation_ids)),
    }
    if has_window:
        placeholders["start_dt"] = ast.Constant(value=window_start)
        placeholders["end_dt"] = ast.Constant(value=window_end)

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="GenerationContentsForLabeling",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    return {
        row[0]: {
            "model": row[1] or None,
            # $ai_input and $ai_output_choices come back as JSON-serialized strings
            # (arrays of message dicts / choice dicts). Keep them as-is — the labeling
            # agent will receive them as strings and doesn't need structured access.
            "input": _truncate(row[2], max_input_chars),
            "output": _truncate(row[3], max_output_chars),
        }
        for row in (result.results or [])
        if row[0]
    }


def fetch_evaluator_configs(team: Team, evaluator_ids: list[str]) -> dict[str, dict]:
    """Fetch full Evaluation config rows keyed by evaluator id (as string).

    Used by the labeling agent's ``get_evaluator_config`` tool — when it wants to
    ground a cluster label in the evaluator's rubric (the llm_judge prompt, or the
    hog code) rather than inferring from reasoning text alone. Bounded because
    teams have a handful of distinct evaluators, not thousands.
    """
    # Local import so data.py doesn't pull the Django Evaluation model into the
    # workflow-side import graph (matches the pattern in sampling.py).
    from products.llm_analytics.backend.models.evaluations import Evaluation

    ids = {eid for eid in evaluator_ids if eid}
    if not ids:
        return {}

    rows = Evaluation.objects.filter(team_id=team.id, id__in=ids).values(
        "id", "name", "description", "evaluation_type", "evaluation_config", "output_type", "output_config"
    )
    return {str(r["id"]): dict(r) for r in rows}


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    s = str(value)
    if len(s) <= limit:
        return s
    return s[:limit] + f"… [{len(s) - limit} more chars]"


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
