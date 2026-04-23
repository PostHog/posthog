"""Tool definitions for the evaluation cluster-labeling agent.

Parallel to ``trace_clustering.labeling_agent.tools`` — same InjectedState
pattern, same label-setting semantics — but the content-rendering tools
surface evaluation-specific fields (verdict, reasoning, evaluator name)
instead of trace summaries.
"""

import json
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


def _title_for_eval(eval_id: str, state: dict) -> str:
    """Render the short title the agent sees for an eval in overview passes."""
    content = state["all_eval_contents"].get(eval_id)
    if not content:
        return eval_id
    name = content.get("evaluation_name") or "Evaluation"
    verdict = content.get("verdict") or "unknown"
    return f"{name}: {verdict}"


@tool
def get_clusters_overview(
    state: Annotated[dict, InjectedState],
) -> str:
    """High-level overview: cluster IDs, sizes, and 2D centroid positions.

    Start here to understand what clusters exist and their relative sizes.
    """
    overviews = []
    for cluster_id, cluster_data in state["cluster_data"].items():
        overviews.append(
            {
                "cluster_id": cluster_id,
                "size": cluster_data["size"],
                "centroid_x": cluster_data["centroid_x"],
                "centroid_y": cluster_data["centroid_y"],
            }
        )
    return json.dumps(sorted(overviews, key=lambda x: x["cluster_id"]), indent=2)


@tool
def get_all_clusters_with_sample_titles(
    state: Annotated[dict, InjectedState],
    titles_per_cluster: int = 10,
) -> str:
    """**Recommended for Phase 1.** Get ALL clusters with sample evaluation titles in a single call.

    Each title is rendered as "{evaluator_name}: {verdict}" so the agent can
    quickly see the verdict mix and evaluator names in each cluster. Titles
    are sorted by distance to centroid (most representative first).
    """
    result = []
    for cluster_id, cluster_data in state["cluster_data"].items():
        evals_metadata = cluster_data["evals"]
        sorted_evals = sorted(evals_metadata.items(), key=lambda x: x[1]["rank"])
        sample_titles = [_title_for_eval(eval_id, state) for eval_id, _ in sorted_evals[:titles_per_cluster]]
        result.append(
            {
                "cluster_id": cluster_id,
                "size": cluster_data["size"],
                "sample_titles": sample_titles,
            }
        )
    return json.dumps(sorted(result, key=lambda x: x["cluster_id"]), indent=2)


@tool
def get_cluster_eval_titles(
    state: Annotated[dict, InjectedState],
    cluster_id: int,
    limit: int = 30,
) -> str:
    """Lightweight list of evaluator + verdict titles for one cluster.

    Use this to scan what's in a cluster without pulling full reasoning text.
    ``rank`` indicates distance to centroid (1 = most representative); edge
    ranks may reveal sub-patterns worth drilling into with ``get_eval_reasoning``.
    """
    cluster_data = state["cluster_data"].get(cluster_id)
    if not cluster_data:
        return json.dumps([])

    evals_metadata = cluster_data["evals"]
    infos = []
    for eval_id, metadata in evals_metadata.items():
        infos.append(
            {
                "eval_id": eval_id,
                "title": _title_for_eval(eval_id, state),
                "rank": metadata["rank"],
                "distance_to_centroid": metadata["distance_to_centroid"],
                "x": metadata["x"],
                "y": metadata["y"],
            }
        )
    infos.sort(key=lambda x: x["rank"])
    return json.dumps(infos[:limit], indent=2)


@tool
def get_eval_reasoning(
    state: Annotated[dict, InjectedState],
    eval_ids: list[str],
) -> str:
    """Get the evaluator's full reasoning text plus its verdict, runtime, and linked generation metadata.

    This surfaces what the evaluator itself *said* about each item — the free-text
    ``$ai_evaluation_reasoning`` that was embedded for clustering. Use when the
    short "{evaluator_name}: {verdict}" titles aren't enough to see the shared
    pattern. Cheap — all returned fields already live in state, no DB call.

    For grounding outside the evaluator's own voice, reach for:
    - ``get_generation_details`` to read the generation's input/output that the
      evaluator was judging.
    - ``get_evaluator_config`` to read the evaluator's rubric (llm_judge prompt
      or hog source).
    """
    details = []
    contents = state["all_eval_contents"]
    for eval_id in eval_ids:
        content = contents.get(eval_id)
        if not content:
            continue
        details.append(
            {
                "eval_id": eval_id,
                "evaluation_name": content.get("evaluation_name"),
                "verdict": content.get("verdict"),
                "reasoning": content.get("reasoning"),
                "runtime": content.get("runtime"),
                "generation_model": content.get("generation_model"),
                "is_error": content.get("is_error"),
                "judge_cost_usd": content.get("judge_cost_usd"),
            }
        )
    return json.dumps(details, indent=2)


@tool
def get_current_labels(
    state: Annotated[dict, InjectedState],
) -> str:
    """Review all cluster labels set so far; useful for distinctiveness checks."""
    result: dict[int, dict[str, str] | None] = {}
    for cluster_id in state["cluster_data"].keys():
        label = state["current_labels"].get(cluster_id)
        if label:
            result[cluster_id] = {"title": label.title, "description": label.description}
        else:
            result[cluster_id] = None
    return json.dumps(result, indent=2)


@tool
def set_cluster_label(
    state: Annotated[dict, InjectedState],
    cluster_id: int,
    title: str,
    description: str,
) -> str:
    """Set or update the label for a specific cluster.

    Title should be 3-10 words naming the shared evaluation pattern (e.g.
    "Factuality failures on multi-hop questions"). Description should be 2-5
    bullet points explaining what the evaluations have in common —
    the failure mode, the evaluator rationale, the kind of generation input
    they target.
    """
    state["current_labels"][cluster_id] = ClusterLabel(title=title, description=description)
    return f"Label set for cluster {cluster_id}: '{title}'"


@tool
def bulk_set_labels(
    state: Annotated[dict, InjectedState],
    labels: list[dict],
) -> str:
    """Set initial labels for many clusters in one call.

    Use this in Phase 1 so every cluster has at least a rough label before
    refinement begins.
    """
    for entry in labels:
        cluster_id = entry["cluster_id"]
        state["current_labels"][cluster_id] = ClusterLabel(
            title=entry["title"],
            description=entry["description"],
        )
    return f"Labels set for {len(labels)} clusters: {[e['cluster_id'] for e in labels]}"


@tool
def get_generation_details(
    state: Annotated[dict, InjectedState],
    eval_ids: list[str],
    max_evals: int = 3,
) -> str:
    """Fetch the linked $ai_generation's input/output text for the given evaluations.

    Use **sparingly** — at most 3 representative evals per call — when the evaluator's
    reasoning alone leaves you uncertain about the cluster's shared pattern. Seeing the
    actual prompt/output the evaluator reacted to can sharpen a label, but the goal is
    still cluster-wide patterns, not deep-reading any single generation.

    Returns ``{eval_id, generation_id, model, input, output}`` per eval. Input/output
    text is truncated to bound token usage. Evaluations with no linked generation
    (or purged generations) are silently skipped.
    """
    # Local import to keep the workflow-side import graph clean of data-layer deps.
    from posthog.models.team import Team
    from posthog.temporal.llm_analytics.evaluation_clustering.data import fetch_generation_contents

    # Resolve eval_id → target_generation_id from state; skip anything missing.
    contents = state["all_eval_contents"]
    pairs: list[tuple[str, str]] = []
    for eval_id in eval_ids[:max_evals]:
        c = contents.get(eval_id)
        if c and c.get("target_generation_id"):
            pairs.append((eval_id, c["target_generation_id"]))
    if not pairs:
        return json.dumps([])

    team = Team.objects.get(id=state["team_id"])
    generation_ids = [gen_id for _, gen_id in pairs]
    # Pass the clustering-run window through so ClickHouse can prune date partitions
    # on the `(team_id, toDate(timestamp))` primary index. Without bounds this would
    # full-scan the team for a handful of UUIDs.
    from datetime import datetime

    def _parse(ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None

    fetched = fetch_generation_contents(
        team=team,
        generation_ids=generation_ids,
        window_start=_parse(state.get("window_start")),
        window_end=_parse(state.get("window_end")),
    )

    result = []
    for eval_id, gen_id in pairs:
        gen = fetched.get(gen_id)
        if gen is None:
            # Generation purged or missing — tell the agent so it doesn't silently
            # assume the eval has no linked generation.
            result.append({"eval_id": eval_id, "generation_id": gen_id, "missing": True})
            continue
        result.append(
            {
                "eval_id": eval_id,
                "generation_id": gen_id,
                "model": gen["model"],
                "input": gen["input"],
                "output": gen["output"],
            }
        )
    return json.dumps(result, indent=2)


@tool
def get_evaluator_config(
    state: Annotated[dict, InjectedState],
    evaluator_id: str | None = None,
    evaluator_name: str | None = None,
) -> str:
    """Fetch the full Evaluation config (name, description, prompt / hog code, output shape).

    Provide exactly one of ``evaluator_id`` (the $ai_evaluation_id UUID) or
    ``evaluator_name`` (resolved via state). Use this to ground a cluster label in
    the evaluator's actual rubric — the llm_judge prompt, the hog source, the N/A
    config, the output schema — rather than inferring it from reasoning alone.

    Returns the row as a dict with ``evaluation_config`` and ``output_config``
    expanded. Hog code lives under ``evaluation_config.hog_source`` for runtime=hog,
    llm_judge prompts under ``evaluation_config.prompt``.
    """
    from posthog.models.team import Team
    from posthog.temporal.llm_analytics.evaluation_clustering.data import fetch_evaluator_configs

    if not evaluator_id and not evaluator_name:
        return json.dumps({"error": "Provide evaluator_id or evaluator_name"})

    # Resolve by name via state if id not given. Evaluation names are not
    # guaranteed unique on a team — if the same name maps to multiple
    # evaluator IDs, return an error asking for evaluator_id so the agent
    # doesn't silently ground on a mismatched rubric.
    resolved_id = evaluator_id
    if not resolved_id and evaluator_name:
        matches: set[str] = set()
        for c in state["all_eval_contents"].values():
            if c.get("evaluation_name") == evaluator_name and c.get("evaluation_id"):
                matches.add(c["evaluation_id"])
        if not matches:
            return json.dumps({"error": f"No evaluation_id found for name {evaluator_name!r}"})
        if len(matches) > 1:
            return json.dumps(
                {
                    "error": f"Evaluation name {evaluator_name!r} resolves to multiple evaluator IDs; "
                    "pass evaluator_id to disambiguate",
                    "matching_evaluator_ids": sorted(matches),
                }
            )
        resolved_id = next(iter(matches))

    team = Team.objects.get(id=state["team_id"])
    configs = fetch_evaluator_configs(team=team, evaluator_ids=[resolved_id])
    config = configs.get(resolved_id)
    if config is None:
        return json.dumps({"error": f"No Evaluation row for id {resolved_id}"})

    # Stringify UUID for JSON
    config = {**config, "id": str(config.get("id"))}
    return json.dumps(config, indent=2, default=str)


@tool
def finalize_labels(
    state: Annotated[dict, InjectedState],
) -> str:
    """Signal that every cluster has a satisfactory, distinctive label."""
    labeled_count = sum(1 for label in state["current_labels"].values() if label is not None)
    total_count = len(state["cluster_data"])
    return f"Finalized! {labeled_count}/{total_count} clusters labeled."


EVAL_LABELING_TOOLS = [
    get_clusters_overview,
    get_all_clusters_with_sample_titles,
    get_cluster_eval_titles,
    get_eval_reasoning,
    get_generation_details,
    get_evaluator_config,
    get_current_labels,
    set_cluster_label,
    bulk_set_labels,
    finalize_labels,
]
