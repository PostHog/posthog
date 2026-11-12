import json
import dataclasses
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.engines import (
    ClaudeWebSearchEngine,
    ExaAnswerEngine,
    OpenAIWebSearchEngine,
    PerplexityWebSearchEngine,
)
from products.aeo.backend.runner import run_citation_checks

ENGINES_BY_NAME = {
    "claude": ClaudeWebSearchEngine,
    "openai": OpenAIWebSearchEngine,
    "exa": ExaAnswerEngine,
    "perplexity": PerplexityWebSearchEngine,
}


class Command(BaseCommand):
    help = (
        "Run AEO citation checks for a team. "
        "Smoke test (runs engines, records nothing): --limit 3 --dry-run. "
        "Note: engines make real, billed API calls even with --dry-run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--limit", type=int, help="Max prompts this run (default AEO_MAX_PROMPTS_PER_RUN).")
        parser.add_argument(
            "--engines",
            type=str,
            help="Comma-separated subset of: claude,openai,exa,perplexity. Default: all configured.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Run engines but record no checks.")

    def handle(self, *args: Any, **options: Any) -> None:
        engines = None
        if options["engines"]:
            engines = []
            for name in options["engines"].split(","):
                name = name.strip()
                if name not in ENGINES_BY_NAME:
                    raise CommandError(f"Unknown engine '{name}' — choose from {sorted(ENGINES_BY_NAME)}")
                # Until AEO_PERPLEXITY_ENABLED is on, Perplexity output must not be stored, so only a
                # dry run (for example, to measure cost) may call it.
                if name == "perplexity" and not settings.AEO_PERPLEXITY_ENABLED and not options["dry_run"]:
                    raise CommandError(
                        "The perplexity engine runs only with --dry-run until AEO_PERPLEXITY_ENABLED is on"
                    )
                try:
                    engines.append(ENGINES_BY_NAME[name]())
                except ValueError as e:
                    raise CommandError(str(e))

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")

        summary, checks = run_citation_checks(
            team,
            engines=engines,
            limit=options["limit"],
            record=not options["dry_run"],
        )

        for check in checks:
            marker = "CITED" if check["cited"] else ("FAILED" if check["check_failed"] else "not cited")
            self.stdout.write(f"\n[{check['engine']}] {marker} — {check['prompt_text'][:80]}")
            for url in check["cited_urls"][:10]:
                self.stdout.write(f"    {url}")
            if check.get("error"):
                self.stdout.write(self.style.ERROR(f"    error: {check['error']}"))

        costs = [check["cost_usd"] for check in checks if check.get("cost_usd") is not None]
        if costs:
            self.stdout.write(f"\nEngine-reported cost: ${sum(costs):.4f} over {len(costs)} checks")

        self.stdout.write(self.style.SUCCESS(f"\n{json.dumps(dataclasses.asdict(summary), indent=2)}"))
