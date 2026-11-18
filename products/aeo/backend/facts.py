"""Facts about an answer that depend on nothing but the answer: the URLs it cites and the searches
the engine ran.

They are written once, when the check is, as one narrow row each. The reads that rank cited domains,
pages and searches then count those rows, and never unpack the JSON columns of the wide check row.
"""

from __future__ import annotations

from urllib.parse import urlparse

from products.aeo.backend.models import CHECK_FACT_TEXT_MAX_LENGTH, AEOCheckCitation, AEOCheckSearch, AEOCitationCheck
from products.aeo.backend.rankings import registrable_domain

BACKFILL_BATCH_SIZE = 500


def normalize_search(query: str) -> str:
    """A search as the reads group it: lowercased, with whitespace collapsed."""
    return " ".join(query.split()).lower()


def citation_rows(check: AEOCitationCheck) -> list[AEOCheckCitation]:
    rows: list[AEOCheckCitation] = []
    for position, url in enumerate(check.cited_urls or [], start=1):
        if not isinstance(url, str) or not url:
            continue
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""
        host = host if len(host) <= 255 else ""
        rows.append(
            AEOCheckCitation(
                team_id=check.team_id,
                citation_check_id=check.id,
                created_at=check.created_at,
                position=position,
                url=url[:CHECK_FACT_TEXT_MAX_LENGTH],
                host=host,
                domain=registrable_domain(host) if host else "",
            )
        )
    return rows


def search_rows(check: AEOCitationCheck) -> list[AEOCheckSearch]:
    queries = (
        normalize_search(query)[:CHECK_FACT_TEXT_MAX_LENGTH]
        for query in check.search_queries or []
        if isinstance(query, str)
    )
    return [
        AEOCheckSearch(team_id=check.team_id, citation_check_id=check.id, created_at=check.created_at, query=query)
        # dict.fromkeys drops the repeats and keeps the order the engine searched in.
        for query in dict.fromkeys(queries)
        if query
    ]


def write_facts(checks: list[AEOCitationCheck]) -> None:
    """Write the fact rows of checks that are already saved. A row that exists is left alone, so a
    repeated call, from a retried run or from the backfill, adds nothing."""
    if not checks:
        return
    # Every check of one call belongs to one team: a run and a backfill page are both per team.
    team_id = checks[0].team_id
    AEOCheckCitation.objects.for_team(team_id, canonical=True).bulk_create(
        [row for check in checks for row in citation_rows(check)], ignore_conflicts=True
    )
    AEOCheckSearch.objects.for_team(team_id, canonical=True).bulk_create(
        [row for check in checks for row in search_rows(check)], ignore_conflicts=True
    )


def backfill_facts(team_id: int) -> int:
    """Write the fact rows of every check of the team. Returns how many checks it read."""
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True).only(
        "id", "team_id", "created_at", "cited_urls", "search_queries"
    )
    read = 0
    last_id = None
    # Keyset pages with a database limit: behind PgBouncer, iterator() would buffer the whole result.
    while page := list((checks.filter(id__gt=last_id) if last_id else checks).order_by("id")[:BACKFILL_BATCH_SIZE]):
        last_id = page[-1].id
        write_facts(page)
        read += len(page)
    return read
