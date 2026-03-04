import json
from typing import Optional

import structlog

from posthog.hogql.ai import hit_openai

logger = structlog.get_logger(__name__)


def generate_refresh_analysis(before_results: dict, after_results: dict, team_id: int) -> Optional[str]:
    """
    Compare before/after dashboard refresh results and return an AI summary of what changed.
    Returns None if there are no significant changes or the AI call fails.
    """
    changes = []

    for tile_id, before in before_results.items():
        after = after_results.get(tile_id)
        if not after:
            continue

        # Skip if data is identical (using default=str to handle datetime and other non-serializable types)
        if json.dumps(before["data"], sort_keys=True, default=str) == json.dumps(
            after["data"], sort_keys=True, default=str
        ):
            continue

        changes.append(
            {
                "insight_name": before.get("insight_name", f"Tile {tile_id}"),
                "before": before["data"],
                "after": after["data"],
            }
        )

    if not changes:
        return None

    # Limit verbosity for large dashboards
    prioritization_instruction = (
        "List ONLY the top 3-5 most significant changes." if len(changes) > 5 else "List the significant changes."
    )

    prompt = (
        "You are a product data analyst. A user just refreshed their dashboard. "
        "Compare the 'before' and 'after' data for the following insights and summarize what changed.\n\n"
        "Style Rules:\n"
        "- Focus ONLY on significant changes (drops, spikes, trend reversals).\n"
        "- If including a summary, put it at the beginning of the response."
        "- If nothing significant changed, say so.\n"
        f"{prioritization_instruction}\n"
        "- Group related findings.\n"
        "- Use concise bullet points.\n"
        "- Be direct and quantify changes when possible (e.g., '+15%', 'dropped by 30%').\n"
        "- Do NOT use markdown formatting (no bold, italics, etc). Use plain text.\n\n"
        f"Changes:\n{json.dumps(changes, default=str)}"
    )

    messages = [{"role": "user", "content": prompt}]
    try:
        content, _, _ = hit_openai(
            messages,
            f"team/{team_id}/dashboard_refresh",
            posthog_properties={
                "ai_product": "product_analytics",
                "ai_feature": "dashboard-refresh-analysis",
            },
        )
        return content
    except Exception:
        logger.exception("dashboard_refresh_analysis_failed")
        return None
