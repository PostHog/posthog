from __future__ import annotations

import re
import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from django.conf import settings
from django.db.models import BooleanField, Case, Q, Value, When

import tldextract

from products.aeo.backend.engines import is_target_url, top_domains
from products.aeo.backend.facade.contracts import CitationGap, EngineAnswer
from products.aeo.backend.models import AEOCitationCheck

MAX_GAP_URLS = 10
MAX_GAP_QUERIES = 10
_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())


def _ranked(counter: Counter[str], limit: int) -> tuple[str, ...]:
    return tuple(value for value, _ in counter.most_common(limit))


def _brand_regex(target_domains: list[str]) -> str | None:
    names = {(_DOMAIN_PARTS(domain).domain or domain).lower() for domain in target_domains if domain}
    if not names:
        return None
    return r"\m(" + "|".join(re.escape(name) for name in sorted(names)) + r")\M"


def list_citation_gaps(team_id: int, *, since: dt.datetime) -> list[CitationGap]:
    target_domains: list[str] = settings.AEO_TARGET_DOMAINS
    checks_in_window = AEOCitationCheck.objects.for_team(team_id).filter(
        created_at__gte=since, check_failed=False, prompt__active=True
    )
    mention = Q(cited=True)
    if brand := _brand_regex(target_domains):
        mention |= Q(answer_text__iregex=brand)
    rows = (
        checks_in_window.annotate(
            mentioned=Case(When(mention, then=Value(True)), default=Value(False), output_field=BooleanField())
        )
        .order_by("-created_at")
        .values(
            "prompt_id",
            "prompt_hash",
            "prompt_text",
            "engine",
            "cited",
            "mentioned",
            "cited_urls",
            "target_urls",
            "search_queries",
            "created_at",
        )
    )
    answers = (
        checks_in_window.exclude(answer_text__isnull=True)
        .exclude(answer_text="")
        .order_by("prompt_id", "engine", "-created_at")
        .distinct("prompt_id", "engine")
        .values("prompt_id", "engine", "answer_text", "created_at")
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["prompt_id"])].append(dict(row))
    latest_answers_by_prompt: dict[str, list[EngineAnswer]] = defaultdict(list)
    for answer in sorted(answers, key=lambda answer: answer["created_at"], reverse=True):
        latest_answers_by_prompt[str(answer["prompt_id"])].append(
            EngineAnswer(
                engine=answer["engine"], answer_text=answer["answer_text"] or "", checked_at=answer["created_at"]
            )
        )

    gaps: list[CitationGap] = []
    for prompt_id, checks in grouped.items():
        cited_checks = sum(1 for check in checks if check["cited"])
        if cited_checks == len(checks):
            continue
        mentioned_checks = sum(1 for check in checks if check["mentioned"])

        engines = sorted({check["engine"] for check in checks})
        engines_citing = {check["engine"] for check in checks if check["cited"]}
        competitor_urls: Counter[str] = Counter()
        queries: Counter[str] = Counter()
        our_urls: Counter[str] = Counter()
        for check in checks:
            competitor_urls.update(url for url in check["cited_urls"] or [] if not is_target_url(url, target_domains))
            queries.update(check["search_queries"] or [])
            our_urls.update(check["target_urls"] or [])

        ranked_competitor_urls = _ranked(competitor_urls, MAX_GAP_URLS)
        domain_counts: Counter[str] = Counter()
        for url, count in competitor_urls.items():
            for domain in top_domains([url]):
                domain_counts[domain] += count

        latest = checks[0]
        gaps.append(
            CitationGap(
                prompt_id=prompt_id,
                prompt_hash=latest["prompt_hash"],
                prompt_text=latest["prompt_text"],
                checks=len(checks),
                cited_checks=cited_checks,
                mentioned_checks=mentioned_checks,
                engines=tuple(engines),
                engines_not_citing=tuple(engine for engine in engines if engine not in engines_citing),
                competitor_urls=ranked_competitor_urls,
                competitor_domains=_ranked(domain_counts, MAX_GAP_URLS),
                engine_search_queries=_ranked(queries, MAX_GAP_QUERIES),
                our_cited_urls=_ranked(our_urls, MAX_GAP_URLS),
                latest_answers=tuple(latest_answers_by_prompt[prompt_id]),
                last_checked_at=latest["created_at"],
            )
        )

    return sorted(gaps, key=lambda gap: (gap.cited_checks / gap.checks, -gap.checks))
