"""LLM-based cluster labeling for MCP intent clusters.

This is intentionally simpler than the LLM analytics labeling agent — intents are
short strings and we only need a one-shot title/description/gap_score per cluster.
"""

import json

import structlog
from pydantic import BaseModel, Field

from posthog.temporal.mcp_analytics.models import ClusterLabel, IntentStat

from products.llm_analytics.backend.llm import Client, CompletionRequest
from products.llm_analytics.backend.llm.config import get_eval_config

logger = structlog.get_logger(__name__)

LABELING_MODEL = "gpt-5-mini"
LABELING_PROVIDER = "openai"

_SYSTEM_PROMPT = """\
You label clusters of user / agent intents collected from MCP (Model Context Protocol) tool calls.

For each cluster you receive:
- A list of sample intents (what users / agents were trying to accomplish)
- Aggregate failure signal: error rate, empty-response rate, distinct tools attempted

Produce:
- A one-line **title** naming the underlying intent (max 8 words)
- A short **description** (1-2 sentences) explaining what users are trying to do
- A **gap_score** from 0 to 1 estimating how likely this cluster represents a missing tool capability

Higher gap_score means: high error rate, high empty-response rate, lots of distinct tools tried (the agent
was shopping for a tool that doesn't exist), or intents that explicitly describe an action no available
tool supports. Lower gap_score means: low error rate, a clear dominant tool — this cluster is probably
covered already.

Return ONLY a JSON object matching the schema. Do not include markdown fences or commentary.
"""


class _LabelResponse(BaseModel):
    title: str = Field(max_length=120)
    description: str = Field(max_length=500)
    gap_score: float = Field(ge=0.0, le=1.0)


def _build_user_prompt(samples: list[IntentStat]) -> str:
    bullets = []
    for s in samples[:25]:
        bullets.append(
            f"- {s.intent!r} — {s.total_calls} calls, "
            f"{s.error_rate:.0%} errors, {s.empty_rate:.0%} empty responses, "
            f"{s.distinct_tools_attempted} distinct tools attempted (dominant tool: {s.dominant_tool or 'n/a'})"
        )
    return "Cluster sample intents:\n" + "\n".join(bullets)


def label_cluster(samples: list[IntentStat]) -> ClusterLabel:
    """Label a single cluster via a one-shot LLM call.

    Falls back to a deterministic placeholder label if the LLM call fails, so the
    pipeline never blocks waiting on labeler reliability.
    """
    if not samples:
        return ClusterLabel(title="Empty cluster", description="", gap_score=0.0)

    try:
        client = Client(
            provider_key=None,
            config=get_eval_config(LABELING_PROVIDER),
            capture_analytics=False,
        )
        response = client.complete(
            CompletionRequest(
                model=LABELING_MODEL,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_prompt(samples)}],
                provider=LABELING_PROVIDER,
                response_format=_LabelResponse,
            )
        )
        if isinstance(response.parsed, _LabelResponse):
            parsed = response.parsed
        else:
            if not response.content:
                raise ValueError("LLM returned empty content")
            parsed = _LabelResponse.model_validate(json.loads(response.content))
        return ClusterLabel(title=parsed.title, description=parsed.description, gap_score=parsed.gap_score)
    except Exception as e:
        logger.warning(
            "mcp_analytics_label_cluster_failed",
            error=str(e),
            sample_count=len(samples),
            dominant_intent=samples[0].intent if samples else "",
        )
        # Best-effort fallback so the pipeline emits something useful even if the LLM is down.
        return ClusterLabel(
            title=samples[0].intent[:80] if samples else "Unlabeled cluster",
            description="Auto-labelled fallback (LLM labeler unavailable).",
            gap_score=_heuristic_gap_score(samples),
        )


def _heuristic_gap_score(samples: list[IntentStat]) -> float:
    """Fallback gap_score from observable signals when the LLM labeler is unavailable.

    Mirrors what the LLM prompt should weigh: failures, empty responses, and the
    agent shopping across many tools.
    """
    if not samples:
        return 0.0
    avg_error = sum(s.error_rate for s in samples) / len(samples)
    avg_empty = sum(s.empty_rate for s in samples) / len(samples)
    avg_distinct = sum(s.distinct_tools_attempted for s in samples) / len(samples)
    score = 0.4 * avg_error + 0.3 * avg_empty + 0.3 * min(avg_distinct / 5.0, 1.0)
    return round(min(max(score, 0.0), 1.0), 3)
