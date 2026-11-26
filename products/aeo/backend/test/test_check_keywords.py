import uuid
import random
import datetime as dt
from typing import Any

from posthog.test.base import BaseTest

from django.db import connection

from products.aeo.backend.check_keywords import has_new_keywords, match_new_keywords, write_check_keywords
from products.aeo.backend.models import AEOCheckKeyword, AEOCitationCheck, AEOKeyword, AEOPrompt

# The match the keyword report ran over the answer text at read time, before the rows existed.
_READ_TIME_MATCH_SQL = """
    WITH answered AS MATERIALIZED (
        SELECT check_row.id,
            lower(check_row.prompt_text) AS prompt_text,
            lower(coalesce(check_row.answer_text, '')) AS answer_text,
            lower(array_to_string(ARRAY(
                SELECT jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(check_row.search_queries) = 'array' THEN check_row.search_queries ELSE '[]'::jsonb END
                )
            ), E'\\n')) AS searches
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %(team_id)s AND check_row.check_failed = false
    )
    SELECT answered.id, keyword,
        strpos(answered.prompt_text, keyword) > 0 AS in_prompt,
        strpos(answered.searches, keyword) > 0 AS in_searches,
        CASE WHEN strpos(answered.answer_text, keyword) > 0
            THEN (length(answered.answer_text) - length(replace(answered.answer_text, keyword, ''))) / length(keyword)
            ELSE 0
        END AS uses
    FROM answered CROSS JOIN unnest(%(keywords)s::text[]) AS keyword
    WHERE strpos(answered.prompt_text, keyword) > 0 OR strpos(answered.searches, keyword) > 0
        OR strpos(answered.answer_text, keyword) > 0
"""

KEYWORDS = ["aa", "session replay", "café", "c++", "x"]
PIECES = ["aa", "AA", "a", "session", "Replay", "replay", " ", "\n", "café", "CAFÉ", "cafe", "c++", "C+", "x", "İ", "ß"]


class TestKeywordRows(BaseTest):
    def _check(self, rng: random.Random, **fields: Any) -> AEOCitationCheck:
        prompts = AEOPrompt.objects.for_team(self.team.id)
        prompt = prompts.first() or prompts.create(
            team=self.team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )

        def text() -> str:
            return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 14)))

        return AEOCitationCheck.objects.for_team(self.team.id).create(
            team=self.team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
            **{
                "prompt_text": text(),
                "answer_text": text(),
                "search_queries": [text() for _ in range(rng.randint(0, 3))],
                **fields,
            },
        )

    def _rows(self) -> set[tuple[Any, ...]]:
        return {
            (row.citation_check_id, row.keyword.keyword, row.in_prompt, row.in_searches, row.uses)
            for row in AEOCheckKeyword.objects.for_team(self.team.id).select_related("keyword")
        }

    def test_the_rows_hold_what_the_read_time_match_found(self) -> None:
        AEOKeyword.objects.for_team(self.team.id).bulk_create(
            [AEOKeyword(team=self.team, keyword=keyword) for keyword in KEYWORDS]
        )
        rng = random.Random(11)
        checks = [self._check(rng) for _ in range(200)]
        checks += [
            self._check(rng, answer_text="aaaaa"),
            self._check(rng, answer_text=None),
            self._check(rng, search_queries="not a list"),
            self._check(rng, check_failed=True, prompt_text="aa", answer_text="aa"),
        ]

        write_check_keywords(self.team.id, [check.id for check in checks])

        with connection.cursor() as cursor:
            cursor.execute(_READ_TIME_MATCH_SQL, {"team_id": self.team.id, "keywords": KEYWORDS})
            read_time = set(cursor.fetchall())
        assert self._rows() == read_time
        assert len(read_time) > 100

    def test_a_new_keyword_gets_rows_for_every_stored_answer_and_keeps_the_others(self) -> None:
        AEOKeyword.objects.for_team(self.team.id).create(
            team=self.team, keyword="aa", history_matched_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        )
        rng = random.Random(5)
        checks = [self._check(rng) for _ in range(30)]
        write_check_keywords(self.team.id, [check.id for check in checks])
        kept = set(AEOCheckKeyword.objects.for_team(self.team.id).values_list("id", flat=True))
        AEOKeyword.objects.for_team(self.team.id).create(team=self.team, keyword="replay")
        assert has_new_keywords(self.team.id)

        result = match_new_keywords(self.team.id)

        with connection.cursor() as cursor:
            cursor.execute(_READ_TIME_MATCH_SQL, {"team_id": self.team.id, "keywords": ["aa", "replay"]})
            read_time = set(cursor.fetchall())
        assert self._rows() == read_time
        assert (
            set(
                AEOCheckKeyword.objects.for_team(self.team.id)
                .filter(keyword__keyword="aa")
                .values_list("id", flat=True)
            )
            == kept
        )
        assert (result.checks, result.keywords) == (30, 1)
        assert not has_new_keywords(self.team.id)
