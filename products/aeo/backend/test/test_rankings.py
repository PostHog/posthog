import uuid
import random
import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.utils import timezone

from parameterized import parameterized

from products.aeo.backend import rankings
from products.aeo.backend.facts import write_facts
from products.aeo.backend.models import AEOCheckCitation, AEOCitationCheck, AEOPrompt
from products.aeo.backend.rankings import _CITED_FROM_SQL, _Citations, comparable_previous_share
from products.aeo.backend.scope import CheckScope, scope_sql_params

# The reads Rankings ran before the first-citation flags: one distinct count of checks per group.
OLD_DOMAIN_ANSWERS_SQL = f"""
    SELECT citation.domain, count(DISTINCT citation.citation_check_id)
    {_CITED_FROM_SQL}
        AND citation.domain <> ''
    GROUP BY citation.domain
"""
OLD_PAGES_SQL = f"""
    SELECT citation.url, citation.domain, count(DISTINCT citation.citation_check_id)
    {_CITED_FROM_SQL}
        AND citation.domain <> '' AND citation.url <> ''
    GROUP BY citation.url, citation.domain
"""

URLS = [
    "https://example.com/a",
    "https://www.example.com/a",
    "https://docs.example.com/b",
    "https://rival.io/x",
    "https://blog.rival.io/y",
    "https://acme.co.uk/z",
    "not a url",
]
HOSTS = ["example.com", "rival.io", "late.example.org", "other.example.net"]


class TestCitationCounts(BaseTest):
    @parameterized.expand([("all_flagged", 0.0), ("some_written_before_the_flags", 0.5), ("none_flagged", 1.0)])
    def test_counts_the_answers_the_distinct_count_counted(self, _name: str, unflagged_share: float) -> None:
        rng = random.Random(3)
        prompt = AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )
        checks = [
            AEOCitationCheck.objects.for_team(self.team.id).create(
                team=self.team,
                prompt=prompt,
                run_id=uuid.uuid4(),
                prompt_text=prompt.prompt,
                prompt_source=prompt.prompt_source,
                prompt_hash=prompt.prompt_hash,
                engine="exa-answer",
                model="exa-answer",
                mode="no_search" if rng.random() < 0.1 else "web_search",
                check_failed=rng.random() < 0.1,
                cited_urls=[rng.choice(URLS) for _ in range(rng.randint(0, 6))],
                top_cited_domains=rng.sample(HOSTS, rng.randint(0, 2)),
            )
            for _ in range(60)
        ]
        write_facts(checks)
        unflagged = [check.id for check in checks if rng.random() < unflagged_share]
        AEOCheckCitation.objects.for_team(self.team.id).filter(citation_check_id__in=unflagged).update(
            first_of_domain=None, first_of_url=None
        )
        now = timezone.now()
        since, until = now - dt.timedelta(days=1), now + dt.timedelta(days=1)
        params = [self.team.id, since, until, self.team.id, since, until, *scope_sql_params(CheckScope())]
        with connection.cursor() as cursor:
            cursor.execute(OLD_DOMAIN_ANSWERS_SQL, params)
            old_domains = dict(cursor.fetchall())
            cursor.execute(OLD_PAGES_SQL, params)
            old_pages = {(url, domain): count for url, domain, count in cursor.fetchall()}

        citations = _Citations(self.team.id, since=since, until=until, scope_params=scope_sql_params(CheckScope()))
        with patch.object(rankings, "MAX_RANKED_PAGES", 1000):
            pages = citations.top_pages()

        assert old_domains
        assert dict(citations.ranked_domains()) == old_domains
        assert {(page.url, page.domain): page.answers for page in pages} == old_pages


@parameterized.expand(
    [
        ("comparable_window", [100, 40], [80, 20], 0.25),
        ("tracking_started_late", [4000, 1800], [90, 40], None),
        ("at_the_threshold", [100, 40], [25, 5], 0.2),
        ("no_answers_before", [10, 4], [0, 0], None),
    ]
)
def test_comparable_previous_share(_name: str, current: list[int], previous: list[int], expected: float | None) -> None:
    assert comparable_previous_share(current, previous) == expected
