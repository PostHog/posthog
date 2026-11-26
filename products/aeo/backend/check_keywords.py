"""Which keywords of the team's list each answer uses, matched when the answer is stored.

The keyword report counts, per keyword, the checks whose prompt, searches or answer text contain it.
Matching every answer at read time made the report scan the text of the whole window, so the matches
are written once per check and keyword, in `posthog_aeo_check_keyword`, and the report counts rows.

Matching runs in SQL with the expressions the report used: Postgres `lower`, `strpos`, and a count of
uses without overlaps. So a stored row says what the read-time match said for the same check.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.models import AEOCheckKeyword, AEOCitationCheck, AEOKeyword
from products.aeo.backend.stored_results import bump_data_version_on_commit

MATCH_BATCH_SIZE = 1000

# A check's searches are joined with newlines, which a keyword can't contain, so no match spans two
# searches. A failed check has no answer to measure, so it gets no rows.
_WRITE_SQL = """
    WITH answered AS MATERIALIZED (
        SELECT check_row.id, check_row.team_id, check_row.created_at,
            lower(check_row.prompt_text) AS prompt_text,
            lower(coalesce(check_row.answer_text, '')) AS answer_text,
            lower(array_to_string(ARRAY(
                SELECT jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(check_row.search_queries) = 'array' THEN check_row.search_queries ELSE '[]'::jsonb END
                )
            ), E'\\n')) AS searches
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %(team_id)s AND check_row.id = ANY(%(check_ids)s::uuid[])
            AND check_row.check_failed = false
    ),
    matched AS (
        SELECT answered.id AS citation_check_id, answered.team_id, answered.created_at, keyword.id AS keyword_id,
            strpos(answered.prompt_text, keyword.keyword) > 0 AS in_prompt,
            strpos(answered.searches, keyword.keyword) > 0 AS in_searches,
            CASE WHEN strpos(answered.answer_text, keyword.keyword) > 0
                THEN (length(answered.answer_text) - length(replace(answered.answer_text, keyword.keyword, '')))
                    / length(keyword.keyword)
                ELSE 0
            END AS uses
        FROM answered
        JOIN posthog_aeo_keyword AS keyword ON keyword.team_id = %(team_id)s
        WHERE (%(keyword_ids)s::uuid[] IS NULL OR keyword.id = ANY(%(keyword_ids)s::uuid[]))
    )
    INSERT INTO posthog_aeo_check_keyword
        (id, team_id, citation_check_id, keyword_id, created_at, in_prompt, in_searches, uses)
    SELECT gen_random_uuid(), team_id, citation_check_id, keyword_id, created_at, in_prompt, in_searches, uses
    FROM matched
    WHERE in_prompt OR in_searches OR uses > 0
"""


def write_check_keywords(
    team_id: int, check_ids: Sequence[uuid.UUID], *, keyword_ids: Sequence[uuid.UUID] | None = None
) -> int:
    """Write the keyword rows of checks that are already saved, and return how many rows it wrote.

    The rows of these checks are replaced, so a repeated call writes the same rows. With `keyword_ids`,
    only those keywords' rows are replaced; without, every keyword of the team's list is matched."""
    if not check_ids:
        return 0
    team_id = resolve_effective_team_id(team_id)
    with transaction.atomic():
        existing = AEOCheckKeyword.objects.for_team(team_id, canonical=True).filter(citation_check_id__in=check_ids)
        if keyword_ids is not None:
            existing = existing.filter(keyword_id__in=keyword_ids)
        existing.delete()
        with connection.cursor() as cursor:
            cursor.execute(
                _WRITE_SQL,
                {
                    "team_id": team_id,
                    "check_ids": list(check_ids),
                    "keyword_ids": list(keyword_ids) if keyword_ids is not None else None,
                },
            )
            return cursor.rowcount


def _check_id_pages(team_id: int, *, run_id: str | None = None) -> Iterable[list[uuid.UUID]]:
    # Keyset pages from the newest check down, which the team's window index serves.
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True)
    if run_id is not None:
        checks = checks.filter(run_id=run_id)
    query = checks.order_by("-created_at", "-id").values_list("created_at", "id")
    last = None
    while page := list(
        (query.filter(Q(created_at__lt=last[0]) | Q(created_at=last[0], id__lt=last[1])) if last else query)[
            :MATCH_BATCH_SIZE
        ]
    ):
        last = page[-1]
        yield [check_id for _, check_id in page]


@frozen
class KeywordMatchResult:
    checks: int
    keywords: int
    rows: int


def match_new_keywords(team_id: int) -> KeywordMatchResult:
    """Write the rows of the keywords that were never matched against the stored answers: keywords added
    since, and every keyword the rows predate. The runner matches each new check against the whole list,
    so once a keyword's history is matched it stays complete.

    A pass that its task's time limit stops leaves its keywords unmatched, and the next pass writes
    their rows again; the rows are replaced, so the result is the same."""
    team_id = resolve_effective_team_id(team_id)
    keyword_ids = list(
        AEOKeyword.objects.for_team(team_id, canonical=True)
        .filter(history_matched_at__isnull=True)
        .values_list("id", flat=True)
    )
    if not keyword_ids:
        return KeywordMatchResult(checks=0, keywords=0, rows=0)
    read = 0
    written = 0
    for page in _check_id_pages(team_id):
        written += write_check_keywords(team_id, page, keyword_ids=keyword_ids)
        read += len(page)
    AEOKeyword.objects.for_team(team_id, canonical=True).filter(id__in=keyword_ids).update(
        history_matched_at=timezone.now()
    )
    bump_data_version_on_commit(team_id)
    return KeywordMatchResult(checks=read, keywords=len(keyword_ids), rows=written)


def match_run_keywords(team_id: int, run_id: str) -> KeywordMatchResult:
    """Write the keyword rows of one run's checks again, against the list of now. The runner matched them
    against the list of the moment, which a keyword added during the run changed since, and a failed
    write left them without rows."""
    team_id = resolve_effective_team_id(team_id)
    read = 0
    written = 0
    for page in _check_id_pages(team_id, run_id=run_id):
        written += write_check_keywords(team_id, page)
        read += len(page)
    if read:
        bump_data_version_on_commit(team_id)
    return KeywordMatchResult(checks=read, keywords=0, rows=written)


def has_new_keywords(team_id: int) -> bool:
    return AEOKeyword.objects.for_team(team_id, canonical=True).filter(history_matched_at__isnull=True).exists()


@frozen
class KeywordEnrichResult:
    new: KeywordMatchResult
    run: KeywordMatchResult | None


def enrich_check_keywords(team_id: int, *, run_id: str | None = None) -> KeywordEnrichResult:
    """Bring the team's keyword rows up to date: match the history of new keywords, then the run's checks."""
    new = match_new_keywords(team_id)
    run = match_run_keywords(team_id, run_id) if run_id else None
    return KeywordEnrichResult(new=new, run=run)
