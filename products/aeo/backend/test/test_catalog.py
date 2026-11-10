import uuid
from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.aeo.backend.catalog import recompute_own_citations, registrable_domain, sync_brands_from_run
from products.aeo.backend.engines import MAX_URLS_PER_CHECK, own_domains_key
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt


class TestSyncBrandsFromRun(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.prompt = AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team, prompt="best analytics?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )

    def _check(
        self, run_id: str, cited_urls: list[str], *, failed: bool = False, team: Team | None = None, **fields: Any
    ) -> AEOCitationCheck:
        team = team or self.team
        prompt = self.prompt if team == self.team else self._prompt_for(team)
        return AEOCitationCheck.objects.for_team(team.id).create(
            team=team,
            prompt=prompt,
            run_id=run_id,
            prompt_text=self.prompt.prompt,
            prompt_source=self.prompt.prompt_source,
            prompt_hash=self.prompt.prompt_hash,
            engine="claude-web-search",
            model="claude",
            check_failed=failed,
            cited_urls=cited_urls,
            **fields,
        )

    def _prompt_for(self, team: Team) -> AEOPrompt:
        return AEOPrompt.objects.for_team(team.id).create(
            team=team, prompt=self.prompt.prompt, prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )

    def _catalog(self) -> dict[str, dict[str, Any]]:
        return {
            brand.domain: {"name": brand.name, "kind": brand.kind, "status": brand.status}
            for brand in AEOBrand.objects.for_team(self.team.id)
        }

    def test_adds_each_domain_the_run_cited(self) -> None:
        run_id, other_run_id = str(uuid.uuid4()), str(uuid.uuid4())
        self._check(run_id, ["https://docs.amplitude.com/a", "https://amplitude.com/b", "https://www.reddit.com/r/x"])
        self._check(run_id, ["https://docs.example.com/guide", "https://news.ycombinator.com/item"])
        self._check(run_id, ["https://heap.io/failed"], failed=True)
        self._check(other_run_id, ["https://mixpanel.com/other-run"])

        result = sync_brands_from_run(self.team.id, run_id)

        assert (result.domains, result.created) == (4, 4)
        assert self._catalog() == {
            "amplitude.com": {"name": "Amplitude", "kind": BrandKind.UNKNOWN, "status": BrandStatus.SUGGESTED},
            "reddit.com": {"name": "Reddit", "kind": BrandKind.PUBLISHER, "status": BrandStatus.CONFIRMED},
            "example.com": {"name": "Example", "kind": BrandKind.UNKNOWN, "status": BrandStatus.SUGGESTED},
            "news.ycombinator.com": {
                "name": "Ycombinator",
                "kind": BrandKind.PUBLISHER,
                "status": BrandStatus.CONFIRMED,
            },
        }

    def test_later_run_adds_only_new_domains_and_keeps_peoples_edits(self) -> None:
        first_run, second_run = str(uuid.uuid4()), str(uuid.uuid4())
        self._check(first_run, ["https://amplitude.com/a"])
        sync_brands_from_run(self.team.id, first_run)
        AEOBrand.objects.for_team(self.team.id).filter(domain="amplitude.com").update(
            name="Amplitude Analytics", kind=BrandKind.COMPETITOR, status=BrandStatus.CONFIRMED
        )
        self._check(second_run, ["https://amplitude.com/b", "https://statsig.com/a"])

        result = sync_brands_from_run(self.team.id, second_run)

        assert result.created == 1
        assert self._catalog() == {
            "amplitude.com": {
                "name": "Amplitude Analytics",
                "kind": BrandKind.COMPETITOR,
                "status": BrandStatus.CONFIRMED,
            },
            "statsig.com": {"name": "Statsig", "kind": BrandKind.UNKNOWN, "status": BrandStatus.SUGGESTED},
        }

    def test_run_synced_through_a_child_environment_lands_on_the_parent_catalog(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        run_id = str(uuid.uuid4())
        self._check(run_id, ["https://amplitude.com/a"])

        sync_brands_from_run(child.id, run_id)

        assert list(AEOBrand.objects.for_team(child.id).values_list("domain", "team_id")) == [
            ("amplitude.com", self.team.id)
        ]

    @parameterized.expand(
        [
            ("own_domain_added", BrandKind.OWN, BrandStatus.CONFIRMED, False, True),
            ("relabeled_as_competitor", BrandKind.COMPETITOR, BrandStatus.CONFIRMED, True, False),
            ("own_brand_ignored", BrandKind.OWN, BrandStatus.IGNORED, True, False),
            ("already_current", BrandKind.OWN, BrandStatus.CONFIRMED, True, True),
        ]
    )
    def test_recompute_own_citations_follows_the_current_own_domains(
        self, _name: str, kind: BrandKind, status: BrandStatus, stored_cited: bool, expect_cited: bool
    ) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team, name="Example", domain="example.com", kind=kind, status=status, source=BrandSource.MANUAL
        )
        cited_urls = ["https://rival.example.org/a", "https://docs.example.com/b", "https://example.com/c"]
        cited: dict[str, Any] = {"cited": True, "target_urls": cited_urls[1:], "target_best_position": 2}
        not_cited: dict[str, Any] = {"cited": False, "target_urls": [], "target_best_position": None}
        sentiment: dict[str, Any] = {"brand_sentiment": "positive", "brand_sentiment_score": 0.9}
        run_id = str(uuid.uuid4())
        mine = self._check(run_id, cited_urls, **(cited if stored_cited else not_cited), **sentiment)
        failed = self._check(run_id, cited_urls, failed=True, **not_cited)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        stale: dict[str, Any] = {
            "cited": True,
            "target_urls": ["https://stale.example.net/"],
            "target_best_position": 9,
        }
        other = self._check(run_id, cited_urls, team=other_team, **stale, **sentiment)

        changed = recompute_own_citations(self.team.id)

        fields = ("cited", "target_urls", "target_best_position", "brand_sentiment", "brand_sentiment_score")
        expected = (cited if expect_cited else not_cited) | (
            sentiment if stored_cited == expect_cited else {"brand_sentiment": None, "brand_sentiment_score": None}
        )
        assert changed == (0 if stored_cited == expect_cited else 1)
        assert AEOCitationCheck.objects.for_team(self.team.id).filter(id=mine.id).values(*fields).get() == expected
        assert AEOCitationCheck.objects.for_team(self.team.id).filter(id=failed.id).values(*fields).get() == {
            **not_cited,
            "brand_sentiment": None,
            "brand_sentiment_score": None,
        }
        assert AEOCitationCheck.objects.for_team(other_team.id).filter(id=other.id).values(*fields).get() == {
            **stale,
            **sentiment,
        }

    def test_recompute_keeps_a_match_cited_past_the_stored_citations(self) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team,
            name="Example",
            domain="example.com",
            kind=BrandKind.OWN,
            status=BrandStatus.CONFIRMED,
            source=BrandSource.MANUAL,
        )
        stored = [f"https://rival{index}.example.org/" for index in range(MAX_URLS_PER_CHECK)]
        check = self._check(
            str(uuid.uuid4()),
            stored,
            cited=True,
            target_urls=["https://example.com/deep"],
            target_best_position=MAX_URLS_PER_CHECK + 1,
        )

        changed = recompute_own_citations(self.team.id)

        assert changed == 0
        assert AEOCitationCheck.objects.for_team(self.team.id).filter(id=check.id).values(
            "cited", "target_urls", "target_best_position"
        ).get() == {"cited": True, "target_urls": ["https://example.com/deep"], "target_best_position": 41}

    @parameterized.expand(
        [
            ("keyed_for_other_own_domains", ["posthog.com"], True),
            ("recorded_before_the_key", None, False),
            ("keyed_for_the_current_own_domains", ["example.com"], False),
        ]
    )
    def test_recompute_clears_sentiment_scored_for_other_own_domains_even_when_citations_match(
        self, _name: str, stored_domains: list[str] | None, expect_cleared: bool
    ) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team,
            name="Example",
            domain="example.com",
            kind=BrandKind.OWN,
            status=BrandStatus.CONFIRMED,
            source=BrandSource.MANUAL,
        )
        sentiment: dict[str, Any] = {"brand_sentiment": "positive", "brand_sentiment_score": 0.9}
        check = self._check(
            str(uuid.uuid4()),
            ["https://rival.example.org/a"],
            cited=False,
            target_urls=[],
            target_best_position=None,
            own_domains_key=own_domains_key(stored_domains) if stored_domains is not None else None,
            **sentiment,
        )

        changed = recompute_own_citations(self.team.id)

        assert changed == 0
        assert AEOCitationCheck.objects.for_team(self.team.id).filter(id=check.id).values(
            "brand_sentiment", "brand_sentiment_score", "own_domains_key"
        ).get() == {
            **({"brand_sentiment": None, "brand_sentiment_score": None} if expect_cleared else sentiment),
            "own_domains_key": own_domains_key(["example.com"]),
        }

    @parameterized.expand(
        [
            ("subdomain", "https://blog.example.co.uk/post", "example.co.uk"),
            ("uppercase_host", "https://WWW.Example.com/", "example.com"),
            ("no_host", "not a url", None),
            ("bare_suffix", "https://co.uk/", None),
            ("longer_than_the_column", f"https://{'a' * 250}.com/", None),
        ]
    )
    def test_registrable_domain(self, _name: str, url: str, expected: str | None) -> None:
        assert registrable_domain(url) == expected
