"""Per-cluster metric aggregation for Stage B evaluation clustering.

Fills in both operational metrics (cost/latency/tokens/errors — sourced from the
linked $ai_generation event) and eval-specific metrics (pass_rate, na_rate,
dominant_evaluation_name, dominant_runtime, avg_judge_cost) on
:class:`ClusterAggregateMetrics`. All new eval fields stay None for non-eval
levels so the dataclass remains single-typed across the whole pipeline.
"""

from collections import Counter

from posthog.temporal.llm_analytics.evaluation_clustering.data import EvaluationMetadata
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterAggregateMetrics


def aggregate_evaluation_metrics(
    eval_event_ids: list[str],
    labels: list[int],
    metadata: dict[str, EvaluationMetadata],
) -> dict[int, ClusterAggregateMetrics]:
    """Bucket evaluations by cluster label and compute per-cluster metrics.

    ``eval_event_ids`` and ``labels`` are positionally aligned — the same order
    used by the compute activity. ``metadata`` may be missing entries for evals
    whose linked generation was purged; those still contribute to eval-specific
    metrics but contribute None to operational averages.
    """
    by_cluster: dict[int, list[str]] = {}
    for idx, cluster_id in enumerate(labels):
        by_cluster.setdefault(cluster_id, []).append(eval_event_ids[idx])

    result: dict[int, ClusterAggregateMetrics] = {}
    for cluster_id, ids in by_cluster.items():
        result[cluster_id] = _aggregate_single_cluster(ids, metadata)
    return result


def _aggregate_single_cluster(
    eval_event_ids: list[str],
    metadata: dict[str, EvaluationMetadata],
) -> ClusterAggregateMetrics:
    # Operational accumulators (sourced from the linked generation)
    total_cost = 0.0
    cost_count = 0
    total_latency = 0.0
    latency_count = 0
    total_tokens = 0
    token_count = 0
    items_with_errors = 0
    items_with_operational_data = 0

    # Eval-specific accumulators
    pass_count = 0
    na_count = 0
    verdict_count = 0  # evals where we could determine a pass/fail/na verdict
    names: Counter[str] = Counter()
    runtimes: Counter[str] = Counter()
    total_judge_cost = 0.0
    judge_cost_count = 0

    for eval_id in eval_event_ids:
        meta = metadata.get(eval_id)
        if meta is None:
            continue

        # Eval-specific
        if meta.evaluation_name:
            names[meta.evaluation_name] += 1
        if meta.evaluation_runtime:
            runtimes[meta.evaluation_runtime] += 1
        if meta.judge_cost_usd is not None and meta.judge_cost_usd > 0:
            total_judge_cost += meta.judge_cost_usd
            judge_cost_count += 1
        if meta.evaluation_applicable is False:
            na_count += 1
            verdict_count += 1
        elif meta.evaluation_result is True:
            pass_count += 1
            verdict_count += 1
        elif meta.evaluation_result is False:
            verdict_count += 1
        # Else: verdict unknown, skip in pass_rate/na_rate denominators

        # Operational — only counts evals where the linked generation was found
        has_generation = any(
            v is not None
            for v in (
                meta.generation_cost_usd,
                meta.generation_latency_ms,
                meta.generation_input_tokens,
                meta.generation_output_tokens,
                meta.generation_model,
                meta.generation_is_error,
            )
        )
        if has_generation:
            items_with_operational_data += 1
            if meta.generation_is_error:
                items_with_errors += 1
            if meta.generation_cost_usd is not None and meta.generation_cost_usd > 0:
                total_cost += meta.generation_cost_usd
                cost_count += 1
            if meta.generation_latency_ms is not None and meta.generation_latency_ms > 0:
                total_latency += meta.generation_latency_ms
                latency_count += 1
            tokens = (meta.generation_input_tokens or 0) + (meta.generation_output_tokens or 0)
            if tokens > 0:
                total_tokens += tokens
                token_count += 1

    return ClusterAggregateMetrics(
        # Operational
        avg_cost=(total_cost / cost_count) if cost_count else None,
        avg_latency=(total_latency / latency_count) if latency_count else None,
        avg_tokens=(total_tokens / token_count) if token_count else None,
        total_cost=total_cost if cost_count else None,
        error_rate=(items_with_errors / items_with_operational_data) if items_with_operational_data else None,
        error_count=items_with_errors,
        item_count=len(eval_event_ids),
        sentiment=None,  # not applicable for eval clusters
        # Eval-specific
        pass_rate=(pass_count / verdict_count) if verdict_count else None,
        na_rate=(na_count / verdict_count) if verdict_count else None,
        dominant_evaluation_name=names.most_common(1)[0][0] if names else None,
        dominant_runtime=runtimes.most_common(1)[0][0] if runtimes else None,
        avg_judge_cost=(total_judge_cost / judge_cost_count) if judge_cost_count else None,
    )
