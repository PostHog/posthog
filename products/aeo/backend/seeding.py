"""Prompt seeding for the AEO citation-tracking POC.

Derives the candidate prompt set from first-party data — the most defensible
part of the POC, because these are questions real users demonstrably asked or
pages answer engines demonstrably consume, not guesses:

- user_reported: free-text "what prompt led you here" answers from signup
- ai_entry_page: pages where AI-channel sessions land (needs expand=True)
- crawled_content: content paths AI agents crawl (needs expand=True)
- gsc_query: question-shaped search-console queries, when a GSC source is synced

A hand-written control set (source=manual) and CSV imports (source=imported,
e.g. an existing AEO tool's prompt export) run through the identical pipeline
so seeded-vs-manual is a fair comparison.
"""

from __future__ import annotations

import csv
import json
import hashlib
from collections.abc import Callable
from dataclasses import field
from typing import Any

from django.conf import settings

import requests
import structlog

from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.models.team import Team

from products.aeo.backend.engines import gateway_post_json
from products.aeo.backend.models import AEOPrompt

logger = structlog.get_logger(__name__)

EXPANSION_TIMEOUT_SECONDS = 120
EXPANSION_MAX_TOKENS = 2000
# Words that make a search query look like a question an answer engine would get.
QUESTION_MARKERS = ("how", "what", "which", "why", "best", "vs", "versus", "compare", "alternative", "should")


@frozen
class PromptCandidate:
    text: str
    source: str
    rank: float = 0
    evidence: dict[str, Any] = field(default_factory=dict)


def normalize_prompt(text: str) -> str:
    return " ".join(text.strip().split())


def prompt_hash(text: str) -> str:
    return hashlib.sha256(normalize_prompt(text).lower().encode("utf-8")).hexdigest()


def collect_candidates(
    team: Team,
    *,
    source: str = "all",
    csv_path: str | None = None,
    csv_source: str = AEOPrompt.Source.IMPORTED,
    expand: bool = False,
) -> tuple[list[PromptCandidate], list[str]]:
    """Gather prompt candidates from the requested sources, ranked high-to-low.

    Returns (candidates, notes) — notes are human-readable observations about
    skipped or partial sources, for the command to surface.
    """
    candidates: list[PromptCandidate] = []
    notes: list[str] = []

    if csv_path:
        candidates += import_prompts_csv(csv_path, source=csv_source)

    def best_effort(label: str, fetch: Callable[[], list[Any]]) -> list[Any]:
        # Each first-party source degrades independently: one broken analytics
        # query must not abort the seed run (in particular a CSV import).
        try:
            return fetch()
        except Exception as e:
            logger.exception("aeo_seed_source_unavailable", team_id=team.id, seed_source=label)
            notes.append(f"{label} source unavailable, skipped: {str(e)[:120]}")
            return []

    if source in ("all", "user_reported"):
        candidates += best_effort("user_reported", lambda: fetch_user_reported_prompts(team))
    if source in ("all", "gsc"):
        candidates += best_effort("gsc", lambda: fetch_gsc_queries(team))
    if source in ("all", "ai_entry_pages"):
        entry_paths = best_effort("ai_entry_pages", lambda: fetch_ai_entry_paths(team))
        notes.append(f"AI entry pages observed: {len(entry_paths)}")
        if expand:
            candidates += expand_paths_to_prompts(entry_paths, source=AEOPrompt.Source.AI_ENTRY_PAGE)
        elif entry_paths:
            notes.append("pass expand=True (--expand) to turn AI entry pages into prompts")
    if source in ("all", "crawled_content"):
        crawled_paths = best_effort("crawled_content", lambda: fetch_ai_crawled_paths(team))
        notes.append(f"AI-crawled content paths observed: {len(crawled_paths)}")
        if expand:
            candidates += expand_paths_to_prompts(crawled_paths, source=AEOPrompt.Source.CRAWLED_CONTENT)
        elif crawled_paths:
            notes.append("pass expand=True (--expand) to turn AI-crawled paths into prompts")

    candidates.sort(key=lambda candidate: candidate.rank, reverse=True)
    return candidates, notes


def fetch_user_reported_prompts(team: Team, *, days: int = 90, limit: int = 100) -> list[PromptCandidate]:
    """Prompts users typed into the signup 'what prompt led you here' field — the
    strongest seed: real prompts real users used on real answer engines."""
    response = execute_hogql_query(
        query=f"""
            SELECT trim(toString(properties.referral_source_ai_prompt)) AS prompt, count() AS signups
            FROM events
            WHERE event = 'user signed up'
              AND notEmpty(trim(toString(properties.referral_source_ai_prompt)))
              AND length(trim(toString(properties.referral_source_ai_prompt))) > 12
              AND timestamp >= now() - INTERVAL {int(days)} DAY
            GROUP BY prompt
            ORDER BY signups DESC
            LIMIT {int(limit)}
        """,
        team=team,
    )
    return [
        PromptCandidate(
            text=row[0],
            source=AEOPrompt.Source.USER_REPORTED,
            rank=float(row[1]),
            evidence={"signups": row[1], "window_days": days},
        )
        for row in response.results or []
    ]


def fetch_ai_entry_paths(team: Team, *, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
    """Pages where AI-channel sessions land. These are evidence rows, not prompts —
    they need LLM expansion into questions (see expand_paths_to_prompts)."""
    response = execute_hogql_query(
        query=f"""
            SELECT $entry_pathname AS path, count() AS sessions
            FROM sessions
            WHERE $channel_type = 'AI'
              AND $start_timestamp >= now() - INTERVAL {int(days)} DAY
              AND notEmpty(path)
            GROUP BY path
            ORDER BY sessions DESC
            LIMIT {int(limit)}
        """,
        team=team,
    )
    return [{"path": row[0], "sessions": row[1], "window_days": days} for row in response.results or []]


def fetch_ai_crawled_paths(team: Team, *, days: int = 7, limit: int = 30) -> list[dict[str, Any]]:
    """Content paths AI agents crawl. Asset fetches and Meta's bulk fetcher are
    excluded — they dominate raw counts without reflecting answer-engine interest."""
    response = execute_hogql_query(
        query=f"""
            SELECT toString(properties.$pathname) AS path, count() AS crawls
            FROM events
            WHERE event = '$http_log'
              AND timestamp >= now() - INTERVAL {int(days)} DAY
              AND `$virt_traffic_type` = 'AI Agent'
              AND `$virt_bot_operator` != 'Meta'
              AND path NOT LIKE '%/page-data/%'
              AND NOT match(path, '\\\\.(js|css|json|map|png|jpg|jpeg|gif|svg|ico|webmanifest|txt|xml|woff2?)$')
              AND notEmpty(path)
            GROUP BY path
            ORDER BY crawls DESC
            LIMIT {int(limit)}
        """,
        team=team,
    )
    return [{"path": row[0], "crawls": row[1], "window_days": days} for row in response.results or []]


def fetch_gsc_queries(team: Team, *, limit: int = 50) -> list[PromptCandidate]:
    """Question-shaped queries from a synced Google Search Console source.

    Best-effort: table naming and columns depend on the connected source, so
    failures return an empty list rather than aborting the seed run.
    """
    try:
        response = execute_hogql_query(
            query=f"""
                SELECT query, sum(clicks) AS total_clicks, sum(impressions) AS total_impressions
                FROM googlesearchconsole.search_analytics_by_query
                GROUP BY query
                ORDER BY total_clicks DESC
                LIMIT {int(limit) * 4}
            """,
            team=team,
        )
    except Exception as e:
        logger.info("aeo_seed_gsc_unavailable", team_id=team.id, error=str(e)[:200])
        return []

    candidates = []
    for row in response.results or []:
        query = str(row[0])
        if not any(marker in query.lower().split() for marker in QUESTION_MARKERS):
            continue
        candidates.append(
            PromptCandidate(
                text=query,
                source=AEOPrompt.Source.GSC_QUERY,
                rank=float(row[1] or 0),
                evidence={"clicks": row[1], "impressions": row[2]},
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def expand_paths_to_prompts(rows: list[dict[str, Any]], *, source: str, limit: int = 25) -> list[PromptCandidate]:
    """Turn observed paths (AI-crawled or AI-landed) into candidate questions via
    one gateway LLM call. Skipped (with a log) when the gateway isn't configured."""
    if not rows:
        return []
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        logger.warning("aeo_seed_expansion_skipped_no_gateway", source=source)
        return []

    paths_block = "\n".join(f"- {row['path']} (weight {row.get('sessions') or row.get('crawls')})" for row in rows)
    instruction = (
        "The following website paths are the pages AI answer engines most often consume or send visitors to. "
        "For each path that represents real product content (skip legal pages, login, careers), write ONE question "
        "a potential customer would plausibly ask an AI assistant that this page answers. Phrase it the way a real "
        "user types, without naming any specific vendor. "
        f'Return ONLY a JSON array of objects: [{{"path": "...", "prompt": "..."}}]. At most {limit} entries.\n\n'
        f"{paths_block}"
    )
    session = requests.Session()
    session.trust_env = False
    body = gateway_post_json(
        session,
        gateway.url.rstrip("/") + "/chat/completions",
        {"Authorization": f"Bearer {gateway.api_key}"},
        {
            "model": settings.AEO_OPENAI_MODEL,
            "messages": [{"role": "user", "content": instruction}],
            "max_tokens": EXPANSION_MAX_TOKENS,
        },
        timeout=EXPANSION_TIMEOUT_SECONDS,
    )
    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if not isinstance(content, str) or not content:
        logger.warning("aeo_seed_expansion_empty_response", source=source)
        return []
    try:
        start, end = content.index("["), content.rindex("]") + 1
        entries = json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        logger.warning("aeo_seed_expansion_unparseable", source=source, content=content[:200])
        return []

    weight_by_path = {row["path"]: row.get("sessions") or row.get("crawls") or 0 for row in rows}
    candidates = []
    for entry in entries[:limit]:
        text = entry.get("prompt") if isinstance(entry, dict) else None
        path = entry.get("path") if isinstance(entry, dict) else None
        if not text:
            continue
        candidates.append(
            PromptCandidate(
                text=text,
                source=source,
                rank=float(weight_by_path.get(path, 0)),
                evidence={"path": path, "weight": weight_by_path.get(path, 0)},
            )
        )
    return candidates


def import_prompts_csv(path: str, *, source: str = AEOPrompt.Source.IMPORTED) -> list[PromptCandidate]:
    """Import prompts from a CSV — either a file with a `prompt` header column,
    or a headerless file with one prompt per line."""
    with open(path, newline="") as f:
        first_row = next(csv.reader(f), None)
        f.seek(0)
        has_header = first_row is not None and any(cell.strip().lower() == "prompt" for cell in first_row)
        candidates = []
        if has_header:
            for row in csv.DictReader(f):
                text = next((value for key, value in row.items() if key and key.strip().lower() == "prompt"), None)
                if text and text.strip():
                    candidates.append(PromptCandidate(text=text.strip(), source=source, evidence={"file": path}))
        else:
            for line in f:
                text = line.strip().strip('"')
                if text:
                    candidates.append(PromptCandidate(text=text, source=source, evidence={"file": path}))
    return candidates


def upsert_prompts(team: Team, candidates: list[PromptCandidate]) -> dict[str, int]:
    created = updated = 0
    for candidate in candidates:
        text = normalize_prompt(candidate.text)
        if not text:
            continue
        # for_team scopes the fail-closed manager; team is still passed
        # explicitly because queryset filters don't propagate into row creation.
        _, was_created = AEOPrompt.objects.for_team(team.id).update_or_create(
            team=team,
            prompt_hash=prompt_hash(text),
            defaults={
                "prompt": text,
                "prompt_source": candidate.source,
                "rank": candidate.rank,
                "evidence": candidate.evidence,
                "active": True,
            },
        )
        created += was_created
        updated += not was_created
    return {"created": created, "updated": updated}
