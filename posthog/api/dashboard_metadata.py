"""LLM-backed dashboard title and description generation from tile inventory."""

import json
from typing import Any, Optional

import structlog

from posthog.schema import InsightVizNode

from posthog.hogql.ai import hit_openai

from posthog.api.insight_metadata import InsightMetadata, summarize_query_for_naming
from posthog.models import Team

logger = structlog.get_logger(__name__)

_DASHBOARD_METADATA_BODY_SHARED = """## Layout weighting (critical)
- Tiles are listed in **visual layout order** (earlier = higher on the page / read first). Treat **top-of-dashboard content as higher priority** when deciding what matters.
- Later or peripheral tiles may be **omitted** from the description if they add little beyond what the lead tiles already imply.

## Audience
Readers may have **no prior context**. Optimize for a quick skim: purpose, stakes, what to look at first.

## Text cards (strong signal)
- **User-authored**, often markdown. Usually explains goals or how to read the board—**weight heavily**, especially when the text card appears **early** in the tile list.
- Mine text for intent; do not paste markdown verbatim into `description` unless a short phrase is clearly the canonical label.

## Tone and terminology
- **Plain language** over jargon, raw property names, or implementation terms—unless a tile is explicitly about that technical concept.
- **No** numeric or opaque ids (user ids, PKs, etc.). Paraphrase; drop id-like tokens.

## Concision overrides polish
- Prefer **density and directness** over eloquence. Short phrases and **sentence fragments OK**; minor grammar tradeoffs acceptable if the line reads faster.

## Description (`description`)
- **Markdown allowed and expected** where it helps scanning: wrap **short phrases in bold** to **call out** what matters—key outcomes, risks, metrics, decisions, or what to watch. **Do not** bold whole sentences or stack bold on every clause; a few sharp callouts beat a wall of plain text.
- **Extra-compact.** What to decide or watch, **outcomes or risks** when tiles imply it.
- **Default: one cohesive block**—a few terse sentences or short lines of prose summarizing the **unified story** (top-weighted tiles). **No headings** unless splitting is clearly justified.
- **Sections only when necessary:** `### Heading` plus a line or two, or a **bold lead-in** line with one line under—**only** if the dashboard has **clearly separate storylines** (e.g. unrelated domains) that would confuse readers in one paragraph. If one narrative fits, **stay single-block**. **Never** invent a section per graph or mirror tile order as a list of headers. When you do split, **prefer a single split** (two blocks); more only if the board is obviously multi-topic.
- Collapse related charts into shared wording; **highest-impact points only**. Still avoid jargon and ids.

## Input — dashboard tiles (layout order: earlier = higher on dashboard, higher inference priority; insight + text only; buttons excluded)
{tiles_summary}

## Output
{output_instructions}
"""


def build_dashboard_tiles_naming_summary(dashboard: Any) -> str:
    """Build a compact text description of insight and text tiles for AI naming (buttons omitted)."""
    from products.dashboards.backend.models.dashboard_tile import DashboardTile

    tiles_qs = DashboardTile.dashboard_queryset(dashboard.tiles.all())
    sorted_tiles = DashboardTile.sort_tiles_by_layout(list(tiles_qs), "sm")
    content_tiles = [t for t in sorted_tiles if t.insight_id or t.text_id]
    if not content_tiles:
        return "(No insight or text tiles on this dashboard.)"

    blocks: list[str] = []
    for i, tile in enumerate(content_tiles, 1):
        if tile.insight is not None:
            insight = tile.insight
            title = (insight.name or insight.derived_name or "Untitled chart").strip()
            block_lines = [f"Tile {i} (insight chart): {title}"]
            if insight.query:
                try:
                    viz = InsightVizNode.model_validate(insight.query)
                    block_lines.append(summarize_query_for_naming(viz))
                except Exception:
                    qdict = insight.query if isinstance(insight.query, dict) else {}
                    kind = qdict.get("kind", "unknown")
                    block_lines.append(f"Visualization kind: {kind}")
            blocks.append("\n".join(block_lines))
        elif tile.text is not None:
            body = (tile.text.body or "").strip()
            # Longer excerpt: text cards are user-authored and often carry markdown context
            excerpt_max = 3500
            excerpt = body[:excerpt_max] + ("..." if len(body) > excerpt_max else "")
            blocks.append(
                f"Tile {i} (**text card — high priority**; user-written context, may include markdown):\n"
                f"{excerpt or '(empty text card)'}"
            )

    return "\n\n".join(blocks)


def generate_dashboard_metadata(
    team: Team,
    tiles_summary: str,
    *,
    current_name: Optional[str] = None,
    current_description: Optional[str] = None,
) -> InsightMetadata:
    """Generate a concise name and description for a dashboard from a pre-built tile summary."""
    try:
        existing_lines: list[str] = []
        if current_name:
            existing_lines.append(f"- Current name: {current_name}")
        if current_description:
            existing_lines.append(f"- Current description: {current_description}")
        existing_block = ""
        if existing_lines:
            existing_block = (
                "## Existing dashboard metadata (foundational context)\n"
                "Use this as grounding: extend, tighten, or replace if outdated—but **do not ignore** wording that still fits.\n"
                + "\n".join(existing_lines)
                + "\n\n"
            )

        task = """## Task
Infer a dashboard **name** and **description** from the tile inventory below. Reflect what is actually on the dashboard (charts and **text cards**), not generic filler. **Do not** enumerate every tile or give **each chart its own subsection**—surface only the **few highest-signal themes**."""
        output_instructions = """Return **only** valid JSON with exactly these string keys: `name`, `description`. No code fences, no commentary. `description` may include markdown (e.g. **bold** callouts). `name` is plain text only—**no markdown** in `name`. Escape strings so the JSON parses (newlines, quotes, backslashes inside `description`)."""
        name_section = """## Name (`name`)
- **One headline**, no newlines. Plain text only—**no markdown** in `name`.
- **Overall theme** from the **weighted** tiles (top + text). Do not default to one chart title unless that tile clearly dominates.

"""
        prompt = f"""{task}

{existing_block}{name_section}{
            _DASHBOARD_METADATA_BODY_SHARED.format(
                tiles_summary=tiles_summary,
                output_instructions=output_instructions,
            )
        }"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You write terse dashboard titles and markdown descriptions: use **bold** sparingly for key callouts; "
                    "one cohesive description by default; section breaks only when storylines are genuinely separate—not one section per chart. "
                    'You output exactly one JSON object with keys "name" and "description" and no other text.'
                ),
            },
            {"role": "user", "content": prompt},
        ]

        content, _, _ = hit_openai(
            messages,
            f"team/{team.id}/generate-dashboard-metadata",
            posthog_properties={
                "ai_product": "analytics_platform",
                "ai_feature": "dashboard-ai-metadata-generation",
            },
        )

        parsed = json.loads(content.strip())
        name = parsed["name"].strip().strip('"').strip("'")
        description = parsed["description"].strip()

        if len(name) > 100:
            name = name[:97] + "..."
        if len(description) > 800:
            description = description[:797] + "..."

        return InsightMetadata(name=name, description=description)

    except Exception:
        logger.exception("ai_dashboard_metadata_generation_failed")
        raise
