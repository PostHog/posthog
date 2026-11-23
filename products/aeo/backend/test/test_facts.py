import uuid
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.models.team import Team

from products.aeo.backend.facts import backfill_facts, has_checks_without_facts, write_facts
from products.aeo.backend.models import AEOCheckCitation, AEOCheckSearch, AEOCitationCheck, AEOPrompt


class TestCheckFacts(BaseTest):
    def _check(self, **fields: Any) -> AEOCitationCheck:
        prompts = AEOPrompt.objects.for_team(self.team.id)
        prompt = prompts.first() or prompts.create(
            team=self.team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )
        return AEOCitationCheck.objects.for_team(self.team.id).create(
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

    @parameterized.expand(
        [
            (
                "subdomain_under_a_multi_part_suffix",
                "https://Blog.Example.co.uk/post",
                "blog.example.co.uk",
                "example.co.uk",
            ),
            ("no_host", "not a url", "", ""),
            ("invalid_host", "https://[bad/path", "", ""),
        ]
    )
    def test_a_cited_url_is_stored_with_its_host_and_registrable_domain(
        self, _name: str, url: str, host: str, domain: str
    ) -> None:
        check = self._check(cited_urls=["https://first.example.com/a", url])

        write_facts([check])

        assert list(
            AEOCheckCitation.objects.for_team(self.team.id)
            .filter(position=2)
            .values_list("citation_check_id", "created_at", "url", "host", "domain")
        ) == [(check.id, check.created_at, url, host, domain)]

    def test_a_host_cited_after_the_stored_urls_gets_a_row_without_a_url(self) -> None:
        check = self._check(
            cited_urls=["https://first.example.com/a"], top_cited_domains=["first.example.com", "late.example.org"]
        )

        write_facts([check])

        assert list(
            AEOCheckCitation.objects.for_team(self.team.id).order_by("position").values_list("url", "host", "domain")
        ) == [
            ("https://first.example.com/a", "first.example.com", "example.com"),
            ("", "late.example.org", "example.org"),
        ]

    def test_a_team_has_checks_without_facts_until_the_backfill_ran(self) -> None:
        self._check(cited_urls=["https://example.com/old"])
        written_by_a_run = self._check(cited_urls=["https://example.com/new"])
        write_facts([written_by_a_run])

        before = has_checks_without_facts(self.team.id)
        backfill_facts(self.team.id)

        assert (before, has_checks_without_facts(self.team.id)) == (True, False)

    def test_a_backfill_that_stopped_early_still_leaves_checks_without_facts(self) -> None:
        self._check(cited_urls=["https://example.com/old"])
        self._check(cited_urls=["https://example.com/new"])
        pages = iter([write_facts])

        def write_one_page_then_stop(checks: list[AEOCitationCheck]) -> None:
            next(pages, self.fail)(checks)

        with (
            patch("products.aeo.backend.facts.BACKFILL_BATCH_SIZE", 1),
            patch("products.aeo.backend.facts.write_facts", write_one_page_then_stop),
            self.assertRaises(AssertionError),
        ):
            backfill_facts(self.team.id)

        assert list(AEOCheckCitation.objects.for_team(self.team.id).values_list("url", flat=True)) == [
            "https://example.com/new"
        ]
        assert has_checks_without_facts(self.team.id)

    def test_the_backfill_command_writes_the_rows_of_every_team_with_checks(self) -> None:
        self._check(cited_urls=["https://example.com/a"])

        call_command("backfill_aeo_check_facts")

        assert AEOCheckCitation.objects.for_team(self.team.id).count() == 1

    def test_backfill_from_a_child_environment_reads_the_checks_of_its_parent(self) -> None:
        self._check(cited_urls=["https://example.com/a"])
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)

        assert backfill_facts(child.id) == 1
        assert AEOCheckCitation.objects.for_team(self.team.id).count() == 1

    def test_searches_are_stored_normalized_once_per_check(self) -> None:
        check = self._check(search_queries=["Best  Replay Tool", "best replay tool ", "", "replay pricing"])

        write_facts([check])

        assert list(
            AEOCheckSearch.objects.for_team(self.team.id).order_by("query").values_list("citation_check_id", "query")
        ) == [(check.id, "best replay tool"), (check.id, "replay pricing")]

    def test_backfill_writes_missing_rows_and_adds_nothing_when_run_again(self) -> None:
        self._check(cited_urls=["https://example.com/a"], search_queries=["replay"])
        already_written = self._check(cited_urls=["https://example.com/b"], search_queries=["funnels"])
        write_facts([already_written])

        assert (backfill_facts(self.team.id), backfill_facts(self.team.id)) == (2, 2)

        assert AEOCheckCitation.objects.for_team(self.team.id).count() == 2
        assert AEOCheckSearch.objects.for_team(self.team.id).count() == 2
