import uuid
from typing import Any

from posthog.test.base import BaseTest

from django.test import override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.aeo.backend.catalog import registrable_domain, sync_brands_from_run
from products.aeo.backend.facade.contracts import BrandKind, BrandStatus
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt


@override_settings(AEO_TARGET_DOMAINS=["posthog.com"])
class TestSyncBrandsFromRun(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.prompt = AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team, prompt="best analytics?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )

    def _check(self, run_id: str, cited_urls: list[str], *, failed: bool = False) -> None:
        AEOCitationCheck.objects.for_team(self.team.id).create(
            team=self.team,
            prompt=self.prompt,
            run_id=run_id,
            prompt_text=self.prompt.prompt,
            prompt_source=self.prompt.prompt_source,
            prompt_hash=self.prompt.prompt_hash,
            engine="claude-web-search",
            model="claude",
            check_failed=failed,
            cited_urls=cited_urls,
        )

    def _catalog(self) -> dict[str, dict[str, Any]]:
        return {
            brand.domain: {"name": brand.name, "kind": brand.kind, "status": brand.status}
            for brand in AEOBrand.objects.for_team(self.team.id)
        }

    def test_adds_each_domain_the_run_cited(self) -> None:
        run_id, other_run_id = str(uuid.uuid4()), str(uuid.uuid4())
        self._check(run_id, ["https://docs.amplitude.com/a", "https://amplitude.com/b", "https://www.reddit.com/r/x"])
        self._check(run_id, ["https://posthog.com/docs", "https://news.ycombinator.com/item"])
        self._check(run_id, ["https://heap.io/failed"], failed=True)
        self._check(other_run_id, ["https://mixpanel.com/other-run"])

        result = sync_brands_from_run(self.team.id, run_id)

        assert (result.domains, result.created) == (4, 4)
        assert self._catalog() == {
            "amplitude.com": {"name": "Amplitude", "kind": BrandKind.UNKNOWN, "status": BrandStatus.SUGGESTED},
            "reddit.com": {"name": "Reddit", "kind": BrandKind.PUBLISHER, "status": BrandStatus.CONFIRMED},
            "posthog.com": {"name": "Posthog", "kind": BrandKind.OWN, "status": BrandStatus.CONFIRMED},
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
            ("subdomain", "https://blog.example.co.uk/post", "example.co.uk"),
            ("uppercase_host", "https://WWW.Example.com/", "example.com"),
            ("no_host", "not a url", None),
            ("bare_suffix", "https://co.uk/", None),
            ("longer_than_the_column", f"https://{'a' * 250}.com/", None),
        ]
    )
    def test_registrable_domain(self, _name: str, url: str, expected: str | None) -> None:
        assert registrable_domain(url) == expected
