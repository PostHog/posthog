"""The prompts and own pages whose visibility changed most between a window and the window before it.

Both reads count stored values: the mention columns of the check for a prompt, and the cited URL rows
for a page.
"""

from __future__ import annotations

import uuid

from django.db import connection
from django.db.models import Count, Q

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import mention_filter
from products.aeo.backend.facade.contracts import (
    MAX_MOVERS,
    MIN_MOVER_ANSWERS,
    CheckMode,
    PageMover,
    PromptMover,
    PromptSetMovers,
)
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.rankings import registrable_domain
from products.aeo.backend.scope import NAMED_SCOPE_SQL, CheckScope, named_scope_sql_params, scope_filter
from products.aeo.backend.window import CheckWindow

# Answered checks that cite each URL on an own domain, in the current window and in the one before.
# Both tables are narrowed by team and time, so each side is read from its own window index.
_OWN_PAGES_SQL = f"""
    SELECT citation.url,
        count(DISTINCT citation.citation_check_id) FILTER (WHERE citation.created_at >= %(window_start)s),
        count(DISTINCT citation.citation_check_id) FILTER (WHERE citation.created_at < %(window_start)s)
    FROM posthog_aeo_check_citation AS citation
    JOIN posthog_aeo_citation_check AS check_row ON check_row.id = citation.citation_check_id
    WHERE citation.team_id = %(team_id)s
        AND citation.created_at >= %(previous_start)s AND citation.created_at < %(until)s
        AND check_row.team_id = %(team_id)s
        AND check_row.created_at >= %(previous_start)s AND check_row.created_at < %(until)s
        AND check_row.check_failed = false AND check_row.mode = 'web_search'
        AND {NAMED_SCOPE_SQL}
        AND citation.domain = ANY(%(own_domains)s) AND citation.url <> ''
    GROUP BY citation.url
"""


@frozen
class _Change:
    """How often something happened among the answers of each window."""

    hits: int
    answers: int
    previous_hits: int
    previous_answers: int

    @property
    def rate(self) -> float:
        return self.hits / self.answers

    @property
    def previous_rate(self) -> float:
        return self.previous_hits / self.previous_answers

    @property
    def change(self) -> float:
        return self.rate - self.previous_rate


def _top_movers[Key](changes: dict[Key, _Change], *, gains: bool) -> list[tuple[Key, _Change]]:
    """The largest gains, or the largest losses, largest first. Ties break on the key, so the order is
    stable between two requests."""
    sign = 1 if gains else -1
    movers = sorted(
        ((key, change) for key, change in changes.items() if sign * change.change > 0),
        key=lambda item: (-sign * item[1].change, str(item[0])),
    )
    return movers[:MAX_MOVERS]


def _prompt_movers(
    movers: list[tuple[uuid.UUID, _Change]], prompts: dict[uuid.UUID, AEOPrompt]
) -> tuple[PromptMover, ...]:
    return tuple(
        PromptMover(
            prompt_id=str(prompt_id),
            prompt=prompts[prompt_id].prompt,
            topic=prompts[prompt_id].topic,
            answers=change.answers,
            mentioned=change.hits,
            mention_rate=change.rate,
            previous_answers=change.previous_answers,
            previous_mentioned=change.previous_hits,
            previous_mention_rate=change.previous_rate,
            change=change.change,
        )
        for prompt_id, change in movers
    )


def _page_movers(movers: list[tuple[str, _Change]]) -> tuple[PageMover, ...]:
    return tuple(
        PageMover(
            url=url,
            answers_citing=change.hits,
            citation_rate=change.rate,
            previous_answers_citing=change.previous_hits,
            previous_citation_rate=change.previous_rate,
            change=change.change,
        )
        for url, change in movers
    )


def get_movers(team_id: int, *, target_domains: list[str], window: CheckWindow, scope: CheckScope) -> PromptSetMovers:
    window_start = window.start
    previous_start = window.previous_start
    until = window.until

    in_current = Q(created_at__gte=window_start)
    in_previous = Q(created_at__lt=window_start)
    answered = AEOCitationCheck.objects.for_team(team_id).filter(
        scope_filter(scope),
        created_at__gte=previous_start,
        created_at__lt=until,
        check_failed=False,
        mode=CheckMode.WEB_SEARCH,
    )
    totals = answered.aggregate(
        answers=Count("id", filter=in_current), previous_answers=Count("id", filter=in_previous)
    )

    prompt_changes: dict[uuid.UUID, _Change] = {
        row["prompt_id"]: _Change(
            hits=row["mentioned"],
            answers=row["answers"],
            previous_hits=row["previous_mentioned"],
            previous_answers=row["previous_answers"],
        )
        for row in answered.filter(prompt__archived_at__isnull=True)
        .values("prompt_id")
        .annotate(
            answers=Count("id", filter=in_current),
            mentioned=Count("id", filter=in_current & mention_filter()),
            previous_answers=Count("id", filter=in_previous),
            previous_mentioned=Count("id", filter=in_previous & mention_filter()),
        )
        .filter(answers__gte=MIN_MOVER_ANSWERS, previous_answers__gte=MIN_MOVER_ANSWERS)
    }
    prompt_gainers = _top_movers(prompt_changes, gains=True)
    prompt_losers = _top_movers(prompt_changes, gains=False)
    prompts = {
        prompt.id: prompt
        for prompt in AEOPrompt.objects.for_team(team_id)
        .filter(id__in=[prompt_id for prompt_id, _ in prompt_gainers + prompt_losers])
        .only("id", "prompt", "topic")
    }

    page_changes: dict[str, _Change] = {}
    # A target like docs.example.com stands for the whole example.com brand.
    own_domains = sorted({registrable_domain(domain.lower()) for domain in target_domains})
    if own_domains and min(totals["answers"], totals["previous_answers"]) >= MIN_MOVER_ANSWERS:
        with connection.cursor() as cursor:
            cursor.execute(
                _OWN_PAGES_SQL,
                {
                    # The ORM reads above map a child environment to its parent; raw SQL has to do the same.
                    "team_id": resolve_effective_team_id(team_id),
                    "window_start": window_start,
                    "previous_start": previous_start,
                    "until": until,
                    "own_domains": own_domains,
                    **named_scope_sql_params(scope),
                },
            )
            page_changes = {
                url: _Change(
                    hits=citing,
                    answers=totals["answers"],
                    previous_hits=previous_citing,
                    previous_answers=totals["previous_answers"],
                )
                for url, citing, previous_citing in cursor.fetchall()
            }
    page_gainers = _top_movers(page_changes, gains=True)
    page_losers = _top_movers(page_changes, gains=False)

    return PromptSetMovers(
        days=window.days,
        window_from=window.window_from,
        window_to=window.window_to,
        branded=scope.segment,
        engine=scope.engine,
        topic=scope.topic,
        answers=totals["answers"],
        previous_answers=totals["previous_answers"],
        min_answers=MIN_MOVER_ANSWERS,
        prompt_gainers=_prompt_movers(prompt_gainers, prompts),
        prompt_losers=_prompt_movers(prompt_losers, prompts),
        page_gainers=_page_movers(page_gainers),
        page_losers=_page_movers(page_losers),
    )
