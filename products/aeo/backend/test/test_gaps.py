import uuid
import datetime as dt

import time_machine
from posthog.test.base import BaseTest

from django.utils import timezone

from products.aeo.backend.facade.api import list_citation_gaps
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt


class TestListCitationGaps(BaseTest):
    def _prompt(self, text: str, *, active: bool = True) -> AEOPrompt:
        return AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team, prompt=text, prompt_hash=text, prompt_source=AEOPrompt.Source.MANUAL, active=active
        )

    def _check(
        self,
        prompt: AEOPrompt,
        engine: str,
        *,
        cited_urls: list[str],
        failed: bool = False,
        answer_text: str | None = None,
        queries: list[str] | None = None,
    ) -> None:
        target_urls = [url for url in cited_urls if "posthog.com" in url]
        AEOCitationCheck.objects.for_team(self.team.id).create(
            team=self.team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine=engine,
            model=engine,
            check_failed=failed,
            cited=bool(target_urls) and not failed,
            cited_urls=cited_urls,
            target_urls=target_urls,
            search_queries=queries or [],
            answer_text=answer_text,
        )

    def test_returns_only_uncited_active_prompts_with_competitor_evidence(self) -> None:
        gap = self._prompt("best session replay tool")
        self._check(
            gap,
            "claude-web-search",
            cited_urls=["https://rival.example/replay", "https://other.example/a"],
            answer_text="Rival is the best, though PostHog also records sessions.",
            queries=["session replay tools"],
        )
        self._check(
            gap,
            "openai-web-search",
            cited_urls=["https://rival.example/replay", "https://posthog.com/session-replay"],
            queries=["session replay tools", "open source replay"],
        )
        self._check(gap, "exa-answer", cited_urls=[], failed=True)

        always_cited = self._prompt("posthog pricing")
        self._check(always_cited, "claude-web-search", cited_urls=["https://posthog.com/pricing"])

        only_failed = self._prompt("engine outage")
        self._check(only_failed, "claude-web-search", cited_urls=[], failed=True)

        inactive = self._prompt("retired prompt", active=False)
        self._check(inactive, "claude-web-search", cited_urls=["https://rival.example/x"])

        gaps = list_citation_gaps(self.team.id, since=timezone.now() - dt.timedelta(days=14))

        assert [g.prompt_text for g in gaps] == ["best session replay tool"]
        result = gaps[0]
        assert result.checks == 2
        assert result.cited_checks == 1
        assert result.mentioned_checks == 2
        assert result.engines == ("claude-web-search", "openai-web-search")
        assert result.engines_not_citing == ("claude-web-search",)
        assert result.competitor_urls[0] == "https://rival.example/replay"
        assert "https://posthog.com/session-replay" not in result.competitor_urls
        assert result.competitor_domains[0] == "rival.example"
        assert result.our_cited_urls == ("https://posthog.com/session-replay",)
        assert result.engine_search_queries[0] == "session replay tools"
        assert [a.answer_text for a in result.latest_answers] == [
            "Rival is the best, though PostHog also records sessions."
        ]

    def test_ignores_checks_before_the_window(self) -> None:
        prompt = self._prompt("old gap")
        with time_machine.travel(timezone.now() - dt.timedelta(days=30), tick=False):
            self._check(prompt, "claude-web-search", cited_urls=["https://rival.example/x"])

        assert list_citation_gaps(self.team.id, since=timezone.now() - dt.timedelta(days=14)) == []
