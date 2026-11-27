import re
import uuid
import random
from concurrent.futures import Future, ThreadPoolExecutor
from io import StringIO
from queue import Queue
from time import monotonic
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.models.team import Team

from products.aeo.backend import check_brands
from products.aeo.backend.check_brands import (
    BrandMatcher,
    brand_identity,
    catalog_identities,
    enrich_check_brands,
    enrich_lock,
    has_stale_brands,
    has_unresolved_checks,
    resolve_stale_brands,
    write_check_brands,
)
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, MentionKind
from products.aeo.backend.facts import write_facts
from products.aeo.backend.models import AEOBrand, AEOCheckBrand, AEOCitationCheck, AEOPrompt

BRAND = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)


def _matcher(name: str, *, aliases: list[str] | None = None, domain: str = "brand.example") -> BrandMatcher:
    return BrandMatcher([brand_identity(BRAND, name=name, aliases=aliases or [], domain=domain)])


def _mentions(matcher: BrandMatcher, text: str) -> list[tuple[str, MentionKind, int]]:
    return [(m.surface, m.kind, m.start) for m in matcher.text_mentions(text).get(BRAND, [])]


class TestBrandMatcher(SimpleTestCase):
    @parameterized.expand(
        [
            ("case_ignored", "Acme", "We like ACME a lot", [("ACME", MentionKind.NAME, 8)]),
            ("possessive", "Acme", "Acme's pricing", [("Acme", MentionKind.NAME, 0)]),
            ("longer_word_is_not_the_name", "Acme", "Acmeify and acmes", []),
            ("underscore_is_a_word_character", "Acme", "acme_tool", []),
            ("multi_word", "Google Analytics", "Try google analytics.", [("google analytics", MentionKind.NAME, 4)]),
            ("multi_word_needs_the_same_spacing", "Google Analytics", "google  analytics", []),
            (
                "trailing_punctuation",
                "Yahoo!",
                "Yahoo! Mail, then yahoo!",
                [("Yahoo!", MentionKind.NAME, 0), ("yahoo!", MentionKind.NAME, 18)],
            ),
            ("trailing_punctuation_then_a_word", "Yahoo!", "yahoo!mail", []),
            ("leading_punctuation", ".NET", "asp.net vs .NET", [(".NET", MentionKind.NAME, 11)]),
            ("first_whole_word_after_a_partial", "Acme", "acmes, then acme", [("acme", MentionKind.NAME, 12)]),
            ("offsets_are_code_points", "Acme", "İİ acme", [("acme", MentionKind.NAME, 3)]),
        ]
    )
    def test_a_name_matches_as_a_whole_phrase(
        self, _name: str, name: str, text: str, expected: list[tuple[str, MentionKind, int]]
    ) -> None:
        assert _mentions(_matcher(name, domain="unrelated.example"), text) == expected

    @parameterized.expand(
        [
            ("alias", "Our pick: ACM.", [("ACM", MentionKind.ALIAS, 10)]),
            ("domain_label", "see acmecorp docs", [("acmecorp", MentionKind.DOMAIN_LABEL, 4)]),
            # A domain mention wins over the label inside it.
            ("bare_domain", "visit acmecorp.com today", [("acmecorp.com", MentionKind.DOMAIN, 6)]),
            ("subdomain", "docs.acmecorp.com.", [("docs.acmecorp.com", MentionKind.DOMAIN, 0)]),
            (
                "url_without_trailing_punctuation",
                "(https://www.acmecorp.com/pricing).",
                [("https://www.acmecorp.com/pricing", MentionKind.URL, 1)],
            ),
            ("email_is_not_a_domain_mention", "mail sales@acmecorp.com", [("acmecorp", MentionKind.DOMAIN_LABEL, 11)]),
        ]
    )
    def test_a_brand_is_found_by_each_of_its_identifiers(
        self, _name: str, text: str, expected: list[tuple[str, MentionKind, int]]
    ) -> None:
        matcher = _matcher("Acme Corp", aliases=["ACM"], domain="acmecorp.com")
        assert _mentions(matcher, text) == expected

    @parameterized.expand(
        [
            ("registrable_domain", "acmecorp.com", [("acmecorp", MentionKind.DOMAIN_LABEL, 0)]),
            ("www_prefix", "www.acmecorp.com", [("acmecorp", MentionKind.DOMAIN_LABEL, 0)]),
            ("site_on_a_subdomain", "news.acmecorp.com", []),
        ]
    )
    def test_only_a_registrable_domain_names_a_brand_by_its_label(
        self, _name: str, domain: str, expected: list[tuple[str, MentionKind, int]]
    ) -> None:
        assert _mentions(_matcher("Daily Wire", domain=domain), "acmecorp news") == expected

    def test_brands_sharing_a_first_word_are_told_apart(self) -> None:
        matcher = BrandMatcher(
            [
                brand_identity(BRAND, name="Google", aliases=[], domain="google.com"),
                brand_identity(OTHER, name="Google Analytics", aliases=[], domain="analytics.example"),
            ]
        )
        found = matcher.text_mentions("Google Analytics beats google search")
        assert [m.start for m in found[BRAND]] == [0, 23]
        assert [m.start for m in found[OTHER]] == [0]

    def test_agrees_with_the_word_regex_the_reads_used_on_random_text(self) -> None:
        names = ["acme", "acme corp", "yahoo!", ".net", "c++", "x"]
        alphabet = ["acme", "corp", "yahoo", "!", ".", "net", "c", "+", "x", " ", "_", "-", "\n", "é"]
        rng = random.Random(7)
        for name in names:
            matcher = _matcher(name, domain="unrelated.example")
            # The word regex of the old competitor reads, with the first match's position.
            regex = re.compile(r"(^|\W)(" + re.escape(name) + r")(?=\W|$)", re.IGNORECASE)
            for _ in range(300):
                text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
                first = regex.search(text)
                found = _mentions(matcher, text)
                with self.subTest(name=name, text=text):
                    assert bool(found) == bool(first)
                    if first:
                        assert found[0][2] == first.start(2)


class TestResolveCheckBrands(BaseTest):
    def _brand(self, domain: str, name: str, **fields: Any) -> AEOBrand:
        return AEOBrand.objects.for_team(self.team.id).create(
            team=self.team, name=name, domain=domain, source=BrandSource.MANUAL, **fields
        )

    def _check(self, *, facts: bool = True, **fields: Any) -> AEOCitationCheck:
        prompts = AEOPrompt.objects.for_team(self.team.id)
        prompt = prompts.first() or prompts.create(
            team=self.team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )
        check = AEOCitationCheck.objects.for_team(self.team.id).create(
            team=self.team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
            **fields,
        )
        if facts:
            write_facts([check])
        return check

    def _rows(self) -> dict[str, tuple[Any, ...]]:
        rows = AEOCheckBrand.objects.for_team(self.team.id).select_related("brand")
        return {
            row.brand.domain: (
                row.mentioned,
                row.cited,
                row.retrieved,
                row.first_position,
                row.citation_position,
                row.matched_by,
            )
            for row in rows
        }

    def _write(self, *checks: AEOCitationCheck) -> None:
        write_check_brands(list(checks), BrandMatcher(catalog_identities(self.team.id)))

    def test_a_check_gets_one_row_per_brand_it_names_cites_or_retrieved(self) -> None:
        self._brand("acme.com", "Acme")
        self._brand("globex.com", "Globex")
        self._brand("initech.com", "Initech")
        self._brand("umbrella.com", "Umbrella")
        check = self._check(
            answer_text="Acme leads, then Globex.",
            cited_urls=["https://other.example/a", "https://docs.globex.com/b"],
            top_cited_domains=["other.example", "docs.globex.com"],
            retrieved_urls=["https://initech.com/c"],
        )

        self._write(check)

        assert self._rows() == {
            "acme.com": (True, False, False, 0, None, MentionKind.NAME),
            "globex.com": (True, True, False, 17, 2, MentionKind.NAME),
            "initech.com": (False, False, True, None, None, MentionKind.RETRIEVAL),
        }
        check.refresh_from_db()
        assert check.brands_resolved_at is not None

    def test_writing_again_replaces_the_rows(self) -> None:
        self._brand("acme.com", "Acme")
        check = self._check(answer_text="Acme")
        self._write(check)

        self._write(check)

        assert AEOCheckBrand.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("new_alias", {"aliases": ["Roadrunner"]}, {"acme.com": True, "globex.com": True}),
            ("rename", {"name": "Roadrunner"}, {"acme.com": True, "globex.com": True}),
            ("no_change", {}, {"globex.com": True}),
        ]
    )
    def test_a_brand_edit_resolves_only_that_brand_again(
        self, _name: str, change: dict[str, Any], expected: dict[str, bool]
    ) -> None:
        acme = self._brand("acme.com", "Acme Inc")
        self._brand("globex.com", "Globex")
        check = self._check(answer_text="Roadrunner and Globex")
        enrich_check_brands(self.team.id)
        assert not has_stale_brands(self.team.id)
        # A row the pass must leave alone: resolving one brand never rewrites another's.
        AEOCheckBrand.objects.for_team(self.team.id).filter(brand__domain="globex.com").update(first_position=99)

        acme.refresh_from_db()
        for field, value in change.items():
            setattr(acme, field, value)
        acme.save()
        assert has_stale_brands(self.team.id) == bool(change)
        resolve_stale_brands(self.team.id)

        rows = AEOCheckBrand.objects.for_team(self.team.id).filter(citation_check=check)
        assert {row.brand.domain: row.mentioned for row in rows.select_related("brand")} == expected
        assert rows.get(brand__domain="globex.com").first_position == 99
        assert not has_stale_brands(self.team.id)

    def test_the_backfill_resolves_old_checks_and_catalogs_every_cited_domain(self) -> None:
        self._brand("acme.com", "Acme", kind=BrandKind.OWN)
        # Recorded before the citation rows existed, which the catalog sync reads.
        old = self._check(
            facts=False,
            answer_text="Acme or Hooli?",
            cited_urls=["https://www.hooli.com/x", "https://news.ycombinator.com/item"],
            top_cited_domains=["www.hooli.com", "news.ycombinator.com"],
        )
        assert has_unresolved_checks(self.team.id)

        result = enrich_check_brands(self.team.id)
        again = enrich_check_brands(self.team.id)

        assert result.brands_added == 2
        assert set(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind")) == {
            ("acme.com", BrandKind.OWN),
            ("hooli.com", BrandKind.UNKNOWN),
            ("news.ycombinator.com", BrandKind.PUBLISHER),
        }
        assert self._rows() == {
            "acme.com": (True, False, False, 0, None, MentionKind.NAME),
            "hooli.com": (True, True, False, 8, 1, MentionKind.NAME),
            "news.ycombinator.com": (False, True, False, None, 2, MentionKind.CITATION),
        }
        assert not has_unresolved_checks(self.team.id)
        assert again.unresolved.checks == 0 and again.stale.brands == 0
        old.refresh_from_db()
        assert old.brands_resolved_at is not None

    def test_a_newer_check_without_rows_is_found_and_resolved(self) -> None:
        self._brand("acme.com", "Acme")
        self._check(answer_text="Acme")
        enrich_check_brands(self.team.id)
        # A check whose rows the runner failed to write, newer than the resolved ones.
        newer = self._check(answer_text="Acme again")

        assert has_unresolved_checks(self.team.id)
        enrich_check_brands(self.team.id)

        assert not has_unresolved_checks(self.team.id)
        assert AEOCheckBrand.objects.for_team(self.team.id).filter(citation_check=newer).count() == 1

    def test_editing_a_parent_brand_leaves_a_subdomain_site_with_its_own_brand(self) -> None:
        parent = self._brand("ycombinator.com", "Y Combinator")
        self._brand("news.ycombinator.com", "Hacker News", kind=BrandKind.PUBLISHER)
        self._check(
            answer_text="Read the thread.",
            cited_urls=["https://news.ycombinator.com/item"],
            top_cited_domains=["news.ycombinator.com"],
            retrieved_urls=["https://news.ycombinator.com/item"],
        )
        enrich_check_brands(self.team.id)
        parent.aliases = ["YC"]
        parent.save()

        resolve_stale_brands(self.team.id)

        assert self._rows() == {"news.ycombinator.com": (False, True, True, None, 1, MentionKind.CITATION)}

    def test_the_backfill_command_skips_a_team_whose_pass_is_running(self) -> None:
        self._brand("acme.com", "Acme")
        self._check(answer_text="Acme")
        lock = enrich_lock(self.team.id, timeout=60)
        assert lock.acquire(blocking=False)
        try:
            output = StringIO()
            call_command("backfill_aeo_check_brands", team_id=self.team.id, stdout=output)
        finally:
            lock.release()

        assert "skipped" in output.getvalue()
        assert has_unresolved_checks(self.team.id)

    @parameterized.expand([("same_names_resume", False, 2), ("edited_again_starts_over", True, 3)])
    def test_a_pass_stopped_by_its_time_limit_resumes_where_it_stopped(
        self, _name: str, edit_again: bool, checks_read_after: int
    ) -> None:
        acme = self._brand("acme.com", "Acme Inc")
        for text in ("Roadrunner one.", "Roadrunner two.", "Roadrunner three."):
            self._check(answer_text=text)
        enrich_check_brands(self.team.id)
        acme.refresh_from_db()
        acme.aliases = ["Roadrunner"]
        acme.save()
        write = check_brands.write_check_brands
        pages: list[int] = []

        def stop_after_the_first_page(*args: Any, **kwargs: Any) -> int:
            if pages:
                raise SoftTimeLimitExceeded()
            pages.append(1)
            return write(*args, **kwargs)

        with (
            patch.object(check_brands, "RESOLVE_BATCH_SIZE", 1),
            patch.object(check_brands, "write_check_brands", side_effect=stop_after_the_first_page),
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            resolve_stale_brands(self.team.id)
        assert has_stale_brands(self.team.id)
        if edit_again:
            acme.refresh_from_db()
            acme.aliases = ["Roadrunner", "Acme"]
            acme.save()

        result = resolve_stale_brands(self.team.id)

        assert result.checks == checks_read_after
        assert AEOCheckBrand.objects.for_team(self.team.id).filter(brand=acme, mentioned=True).count() == 3
        assert not has_stale_brands(self.team.id)

    @parameterized.expand([("a_newer_name", ["Coyote"]), ("back_to_the_old_names", [])])
    def test_a_pass_that_outlived_its_lock_never_writes_over_a_newer_pass(self, _name: str, aliases: list[str]) -> None:
        acme = self._brand("acme.com", "Acme Inc")
        for text in ("Roadrunner one.", "Roadrunner two.", "Roadrunner three."):
            self._check(answer_text=text)
        enrich_check_brands(self.team.id)
        acme.refresh_from_db()
        acme.aliases = ["Roadrunner"]
        acme.save()
        write = check_brands.write_check_brands
        newer_pass_ran: list[bool] = []

        def a_newer_pass_runs_after_the_first_page(*args: Any, **kwargs: Any) -> int:
            written = write(*args, **kwargs)
            if not newer_pass_ran:
                newer_pass_ran.append(True)
                acme.refresh_from_db()
                acme.aliases = aliases
                acme.save()
                resolve_stale_brands(self.team.id)
            return written

        with (
            patch.object(check_brands, "RESOLVE_BATCH_SIZE", 1),
            patch.object(check_brands, "write_check_brands", side_effect=a_newer_pass_runs_after_the_first_page),
        ):
            resolve_stale_brands(self.team.id)

        assert not AEOCheckBrand.objects.for_team(self.team.id).filter(brand=acme).exists()
        assert not has_stale_brands(self.team.id)

    def test_a_failed_check_is_resolved_without_rows(self) -> None:
        self._brand("acme.com", "Acme")
        self._check(check_failed=True, answer_text=None)

        enrich_check_brands(self.team.id)

        assert not has_unresolved_checks(self.team.id)
        assert AEOCheckBrand.objects.for_team(self.team.id).count() == 0


@pytest.mark.django_db(transaction=True)
def test_a_newer_pass_takes_a_brand_over_only_between_pages_of_an_older_one(team: Team) -> None:
    prompt = AEOPrompt.objects.for_team(team.id).create(
        team=team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
    )
    acme = AEOBrand.objects.for_team(team.id).create(
        team=team, name="Acme Inc", domain="acme.com", source=BrandSource.MANUAL
    )
    for text in ("Roadrunner one.", "Roadrunner two.", "Roadrunner three."):
        check = AEOCitationCheck.objects.for_team(team.id).create(
            team=team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
            answer_text=text,
        )
        write_facts([check])
    enrich_check_brands(team.id)
    acme.aliases = ["Roadrunner"]
    acme.save()
    newer_pid: Queue[int] = Queue()

    def newer_pass() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                newer_pid.put(cursor.fetchone()[0])
            AEOBrand.objects.for_team(team.id).filter(id=acme.id).update(aliases=["Coyote"])
            resolve_stale_brands(team.id)
        finally:
            connection.close()

    match = check_brands.check_brand_rows
    started: list[Future[None]] = []

    def start_the_newer_pass_while_matching(*args: Any, **kwargs: Any) -> list[AEOCheckBrand]:
        if not started:
            started.append(pool.submit(newer_pass))
            pid = newer_pid.get(timeout=10)
            # Let the newer pass run until it finishes or waits on this pass's lock.
            deadline = monotonic() + 10
            with connection.cursor() as cursor:
                while not started[0].done() and monotonic() < deadline:
                    cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [connection_pid(), pid])
                    if cursor.fetchone()[0]:
                        break
        return match(*args, **kwargs)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        patch.object(check_brands, "RESOLVE_BATCH_SIZE", 1),
        patch.object(check_brands, "check_brand_rows", side_effect=start_the_newer_pass_while_matching),
    ):
        resolve_stale_brands(team.id)
        started[0].result(timeout=15)

    assert not AEOCheckBrand.objects.for_team(team.id).filter(brand=acme).exists()
    assert not has_stale_brands(team.id)


def connection_pid() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]
