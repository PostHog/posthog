"""What one web search tells about the answers that ran it: the sites they cited, the searches they ran next
to it, the tracked keywords it contains and the prompts it came from.

A citation row belongs to the answer, not to one of its searches, and most answers run several searches.
So a site's share is the share of the answers that ran this search and cited the site, whichever of their
searches surfaced it.
"""

from __future__ import annotations

from django.db import connection

from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend import catalog
from products.aeo.backend.facade.contracts import (
    MAX_DETAIL_DOMAINS,
    MAX_DETAIL_PROMPTS,
    MAX_RELATED_SEARCHES,
    PromptSetDomain,
    PromptSetRelatedSearch,
    PromptSetSearchDetail,
    PromptSetSearchPrompt,
)
from products.aeo.backend.models import AEOKeyword, AEOPrompt
from products.aeo.backend.scope import SCOPE_SQL, CheckScope, scope_sql_params
from products.aeo.backend.window import CheckWindow

# One statement, so the checks that ran the search are found once. `hits` reads the search rows of the
# window from their window index and the check columns from the check's cover index. The citation and
# search rows of those checks then come through their unique indexes, which lead with the check id.
# Every domain is returned, so the own domain gets its rank even outside the top ones.
_SEARCH_DETAIL_SQL = f"""
    WITH hits AS MATERIALIZED (
        SELECT check_row.id, check_row.prompt_id, check_row.engine, check_row.cited
        FROM posthog_aeo_check_search AS search
        JOIN posthog_aeo_citation_check AS check_row ON check_row.id = search.citation_check_id
        WHERE search.team_id = %s AND search.created_at >= %s AND search.created_at < %s AND search.query = %s
            AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s
            AND check_row.check_failed = false AND check_row.mode = 'web_search'
            AND {SCOPE_SQL}
    )
    SELECT
        (SELECT count(*) FROM hits),
        (SELECT count(DISTINCT prompt_id) FROM hits),
        (SELECT count(*) FILTER (WHERE cited) FROM hits),
        (SELECT coalesce(array_agg(DISTINCT engine ORDER BY engine), '{{}}') FROM hits),
        (
            SELECT coalesce(json_agg(json_build_array(domain, answers) ORDER BY answers DESC, domain), '[]')
            FROM (
                SELECT citation.domain, count(DISTINCT citation.citation_check_id) AS answers
                FROM posthog_aeo_check_citation AS citation
                JOIN hits ON hits.id = citation.citation_check_id
                WHERE citation.team_id = %s AND citation.domain <> ''
                GROUP BY citation.domain
            ) AS domains
        ),
        (
            SELECT coalesce(json_agg(json_build_array(query, answers) ORDER BY answers DESC, query), '[]')
            FROM (
                SELECT other.query, count(*) AS answers
                FROM posthog_aeo_check_search AS other
                JOIN hits ON hits.id = other.citation_check_id
                WHERE other.team_id = %s AND other.query <> %s
                GROUP BY other.query
                ORDER BY answers DESC, other.query
                LIMIT %s
            ) AS related
        ),
        (
            SELECT coalesce(array_agg(prompt_id::text ORDER BY answers DESC, prompt_id), '{{}}')
            FROM (
                SELECT prompt_id, count(*) AS answers FROM hits
                GROUP BY prompt_id
                ORDER BY answers DESC, prompt_id
                LIMIT %s
            ) AS prompts
        )
"""


def get_search_detail(team_id: int, query: str, *, window: CheckWindow, scope: CheckScope) -> PromptSetSearchDetail:
    """`query` is a search as the fact rows store it: lowercased, with whitespace collapsed. `keywords` is left
    empty: a keyword edit does not change the data version, so the caller matches them at read."""
    # The ORM reads map a child environment to its parent; raw SQL has to do the same.
    team_id = resolve_effective_team_id(team_id)
    with connection.cursor() as cursor:
        cursor.execute(
            _SEARCH_DETAIL_SQL,
            [
                team_id,
                window.start,
                window.until,
                query,
                team_id,
                window.start,
                window.until,
                *scope_sql_params(scope),
                team_id,
                team_id,
                query,
                MAX_RELATED_SEARCHES,
                MAX_DETAIL_PROMPTS,
            ],
        )
        answers, prompts, cited, engines, domain_rows, related_rows, prompt_ids = cursor.fetchone()

    own = set(catalog.own_domains(team_id))
    target_rank = next((rank for rank, (domain, _) in enumerate(domain_rows, start=1) if domain in own), None)
    texts = {
        str(prompt_id): text
        for prompt_id, text in AEOPrompt.objects.for_team(team_id).filter(id__in=prompt_ids).values_list("id", "prompt")
    }
    return PromptSetSearchDetail(
        query=query,
        window_from=window.window_from,
        window_to=window.window_to,
        answers=answers,
        prompts=prompts,
        cited=cited,
        engines=tuple(engines),
        domains_cited=len(domain_rows),
        target_rank=target_rank,
        # The own domain stays in the list when it ranks below the top ones, so the reader sees where it stands.
        domains=tuple(
            PromptSetDomain(domain=domain, answers=count, share_of_answers=count / answers, is_target=domain in own)
            for rank, (domain, count) in enumerate(domain_rows, start=1)
            if rank <= MAX_DETAIL_DOMAINS or rank == target_rank
        ),
        related_searches=tuple(
            PromptSetRelatedSearch(query=related, answers=count, share_of_answers=count / answers)
            for related, count in related_rows
        ),
        keywords=(),
        top_prompts=tuple(
            PromptSetSearchPrompt(id=prompt_id, text=texts[prompt_id]) for prompt_id in prompt_ids if prompt_id in texts
        ),
    )


def matching_keywords(team_id: int, query: str) -> tuple[str, ...]:
    """The tracked keywords in a search, matched the way the keyword report matches one: as a substring of
    the lowercased search."""
    return tuple(
        keyword
        for keyword in AEOKeyword.objects.for_team(team_id).order_by("keyword").values_list("keyword", flat=True)
        if keyword in query
    )
