"""Facts about an answer that depend on nothing but the answer: the URLs it cites and the searches
the engine ran.

They are written once, when the check is, as one narrow row each. The reads that rank cited domains,
pages and searches then count those rows, and never unpack the JSON columns of the wide check row.
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.db.models import Q

from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.models import CHECK_FACT_TEXT_MAX_LENGTH, AEOCheckCitation, AEOCheckSearch, AEOCitationCheck
from products.aeo.backend.rankings import registrable_domain
from products.aeo.backend.stored_results import bump_data_version_on_commit

BACKFILL_BATCH_SIZE = 500


def normalize_search(query: str) -> str:
    """A search as the reads group it: lowercased, with whitespace collapsed."""
    return " ".join(query.split()).lower()


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host if len(host) <= 255 else ""


def citation_rows(check: AEOCitationCheck) -> list[AEOCheckCitation]:
    urls = [url for url in check.cited_urls or [] if isinstance(url, str) and url]
    cited = [(url, _host(url)) for url in urls]
    # The check keeps the hosts of every citation but only its first URLs. A host cited further down
    # gets a row without a URL, so the count of answers that cite a domain stays whole.
    with_url = {host for _, host in cited}
    beyond = [host.lower() for host in check.top_cited_domains or [] if isinstance(host, str) and host]
    cited += [("", host) for host in dict.fromkeys(beyond) if host not in with_url and len(host) <= 255]
    return [
        AEOCheckCitation(
            team_id=check.team_id,
            citation_check_id=check.id,
            created_at=check.created_at,
            position=position,
            url=url[:CHECK_FACT_TEXT_MAX_LENGTH],
            host=host,
            domain=registrable_domain(host) if host else "",
        )
        for position, (url, host) in enumerate(cited, start=1)
    ]


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


def has_checks_without_facts(team_id: int) -> bool:
    """Whether the team has a check from before the fact rows existed. The backfill writes the newest
    check first and the oldest last, so the oldest check that cites anything has rows only once the
    backfill reached the end."""
    team_id = resolve_effective_team_id(team_id)
    oldest = (
        AEOCitationCheck.objects.for_team(team_id, canonical=True)
        .exclude(cited_urls=[])
        .order_by("created_at", "id")
        .values_list("id", flat=True)
        .first()
    )
    return (
        oldest is not None
        and not AEOCheckCitation.objects.for_team(team_id, canonical=True).filter(citation_check_id=oldest).exists()
    )


def backfill_facts(team_id: int) -> int:
    """Write the fact rows of every check of the team. Returns how many checks it read."""
    # A child environment keeps its checks under its parent, as the runner writes them.
    team_id = resolve_effective_team_id(team_id)
    checks = (
        AEOCitationCheck.objects.for_team(team_id, canonical=True)
        .only("id", "team_id", "created_at", "cited_urls", "top_cited_domains", "search_queries")
        .order_by("-created_at", "-id")
    )
    read = 0
    last: AEOCitationCheck | None = None
    # Keyset pages with a database limit: behind PgBouncer, iterator() would buffer the whole result.
    # They follow (created_at, id) from the newest check down, which the team's window index serves. The
    # oldest check comes last, so `has_checks_without_facts` stays true after a pass that stopped early.
    while page := list(
        (
            checks.filter(Q(created_at__lt=last.created_at) | Q(created_at=last.created_at, id__lt=last.id))
            if last
            else checks
        )[:BACKFILL_BATCH_SIZE]
    ):
        last = page[-1]
        write_facts(page)
        read += len(page)
    bump_data_version_on_commit(team_id)
    return read
