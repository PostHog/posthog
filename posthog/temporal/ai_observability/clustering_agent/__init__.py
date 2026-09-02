"""Shared machinery for LangGraph cluster-labeling agents across analysis levels.

The trace/generation labeling agent (``trace_clustering/labeling_agent``) and the
evaluation labeling agent (``evaluation_clustering/labeling_agent``) are
structurally parallel — same ReAct loop, same ChatOpenAI guardrails, same
default-label fallback. This package holds the mechanics both would otherwise
duplicate; the level-specific prompts, tools, and state TypedDicts live with
each individual agent so per-level prompt iteration stays local.
"""

from collections.abc import Callable, Mapping
from typing import Any

import structlog
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APIStatusError, InternalServerError, RateLimitError

from posthog.temporal.ai_observability.llm_endpoint import build_langchain_chat_client
from posthog.temporal.ai_observability.trace_clustering.constants import NOISE_CLUSTER_ID
from posthog.temporal.ai_observability.trace_clustering.models import ClusterLabel

logger = structlog.get_logger(__name__)

# Deliberately an allowlist rather than the family prefix: OpenAI decides flex eligibility per
# model (gpt-5.4-pro is excluded, for example), so a new labeling model must not inherit the
# flex tier until someone checks the pricing page and adds it here. Keep in sync with
# FLEX_CAPABLE_MODELS in products/ai_observability/backend/summarization/llm/openai.py.
FLEX_CAPABLE_MODELS: frozenset[str] = frozenset({"gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"})

# Per-call timeout for flex labeling calls. It must stay under the ai-gateway's buffered-response
# ceiling (~290s, answered as 504), and it shares the activity's 600s budget with every other
# call the agent makes, so a parked flex call must fail fast enough to leave room for the
# standard-tier rerun.
LABELING_FLEX_CALL_TIMEOUT = 120.0


def get_labeling_llm(
    model: str,
    timeout: float,
    *,
    trace_id: str,
    session_id: str,
    properties: Mapping[str, str],
    distinct_id: str,
    flex: bool = True,
) -> ChatOpenAI:
    """Return a ChatOpenAI client for cluster labeling.

    Shared by the trace and evaluation labeling agents. Routes through the
    ai-gateway when configured; see
    ``posthog.temporal.ai_observability.llm_endpoint``. Enforces the same
    guardrail as before: AI features only run in Cloud or local DEBUG builds.

    Labeling runs as a daily batch, so allowlisted models request the flex
    service tier for half-price tokens. A flex client gets a short per-call
    timeout and no SDK retries: `invoke_labeling_agent` owns recovery, and
    retrying against the same starved tier would only stack timeouts.
    """
    use_flex = flex and model in FLEX_CAPABLE_MODELS
    return build_langchain_chat_client(
        model,
        LABELING_FLEX_CALL_TIMEOUT if use_flex else timeout,
        ai_product="aio_clustering",
        trace_id=trace_id,
        session_id=session_id,
        properties=properties,
        distinct_id=distinct_id,
        service_tier="flex" if use_flex else None,
        max_retries=0 if use_flex else 2,
    )


def _is_flex_recoverable(error: APIError) -> bool:
    """Whether a failed flex agent run should rerun on the standard tier.

    Recoverable: a capacity refusal (429), a connection reset or client timeout
    (APIConnectionError covers its APITimeoutError subclass), any 5xx (the ai-gateway
    answers 504 at its buffered-response ceiling), and 408, which OpenAI's flex docs use
    for a server-side flex timeout and the SDK raises as the bare APIStatusError.
    Anything else is a configuration problem the standard tier shares, so it propagates
    to the caller's default-label handling instead of masking itself behind a rerun.
    """
    if isinstance(error, RateLimitError | APIConnectionError | InternalServerError):
        return True
    return isinstance(error, APIStatusError) and error.status_code == 408


def invoke_labeling_agent(
    make_agent: Callable[[ChatOpenAI], Any],
    initial_state: dict[str, Any],
    config: dict[str, Any],
    *,
    model: str,
    timeout: float,
    trace_id: str,
    session_id: str,
    properties: Mapping[str, str],
    distinct_id: str,
) -> dict[str, Any]:
    """Run a labeling agent on the flex tier, rerunning once on the standard tier if flex fails.

    The labeling callers turn any exception into default cluster labels, so without this
    rerun a flex refusal degrades label quality silently instead of failing. The rerun
    restarts the agent from scratch: completed flex calls are paid twice on this rare path,
    which the tier's discount absorbs.
    """
    llm_kwargs: dict[str, Any] = {
        "trace_id": trace_id,
        "session_id": session_id,
        "properties": properties,
        "distinct_id": distinct_id,
    }
    llm = get_labeling_llm(model, timeout, **llm_kwargs)
    fell_back = False
    try:
        result = make_agent(llm).invoke(initial_state, config)
    except APIError as flex_error:
        if llm.service_tier != "flex" or not _is_flex_recoverable(flex_error):
            raise
        logger.info("labeling_flex_fell_back", error_type=type(flex_error).__name__, model=model)
        fell_back = True
        llm = get_labeling_llm(model, timeout, flex=False, **llm_kwargs)
        result = make_agent(llm).invoke(initial_state, config)
    # The tier the last response reports actually served, so production logs answer whether
    # the gateway forwards service_tier and how often flex refuses.
    logger.info(
        "labeling_served_tier",
        service_tier=_served_tier(result),
        fell_back=fell_back,
        model=model,
    )
    return result


def _served_tier(result: dict[str, Any]) -> str | None:
    for message in reversed(result.get("messages") or []):
        metadata = getattr(message, "response_metadata", None) or {}
        if metadata.get("service_tier"):
            return metadata["service_tier"]
    return None


def fill_missing_labels(
    labels: dict[int, ClusterLabel | None],
    cluster_sizes: dict[int, int],
    *,
    outlier_title: str = "Outliers",
    outlier_description: str = "- Items that didn't fit other clusters\n- May include edge cases or rare patterns",
    fallback_description_singular: str = "similar items",
) -> dict[int, ClusterLabel]:
    """Guarantee every cluster has a label.

    If the agent hit its iteration cap, some clusters may have no label yet.
    This fills in sensible defaults so downstream emission never crashes on
    missing keys. Level-specific callers can override the outlier copy —
    e.g. the evaluation agent uses domain terminology like "Uncategorized
    evaluations" instead of the generic trace wording.
    """
    result: dict[int, ClusterLabel] = {}
    for cluster_id, size in cluster_sizes.items():
        label = labels.get(cluster_id)
        if label is not None:
            result[cluster_id] = label
        elif cluster_id == NOISE_CLUSTER_ID:
            result[cluster_id] = ClusterLabel(title=outlier_title, description=outlier_description)
        else:
            result[cluster_id] = ClusterLabel(
                title=f"Cluster {cluster_id}",
                description=f"- Contains {size} {fallback_description_singular}\n- Label not generated by agent",
            )
    return result


__all__ = ["FLEX_CAPABLE_MODELS", "fill_missing_labels", "get_labeling_llm", "invoke_labeling_agent"]
