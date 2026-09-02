import json
import dataclasses
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.engines import ClaudeWebSearchEngine, ExaAnswerEngine, OpenAIWebSearchEngine
from products.aeo.backend.runner import run_citation_checks

ENGINES_BY_NAME = {
    "claude": ClaudeWebSearchEngine,
    "openai": OpenAIWebSearchEngine,
    "exa": ExaAnswerEngine,
}


class Command(BaseCommand):
    help = (
        "Run AEO citation checks for a team. "
        "Smoke test (runs engines, captures nothing): --limit 3 --dry-run. "
        "Note: engines make real, billed API calls even with --dry-run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--limit", type=int, help="Max prompts this run (default 50).")
        parser.add_argument(
            "--engines",
            type=str,
            help="Comma-separated subset of: claude,openai,exa. Default: all configured.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Run engines but capture no events.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")

        engines = None
        if options["engines"]:
            engines = []
            for name in options["engines"].split(","):
                name = name.strip()
                if name not in ENGINES_BY_NAME:
                    raise CommandError(f"Unknown engine '{name}' — choose from {sorted(ENGINES_BY_NAME)}")
                engines.append(ENGINES_BY_NAME[name]())

        summary, checks = run_citation_checks(
            team,
            engines=engines,
            limit=options["limit"],
            capture=not options["dry_run"],
        )

        for check in checks:
            marker = "CITED" if check["cited"] else ("FAILED" if check["check_failed"] else "not cited")
            self.stdout.write(f"\n[{check['engine']}] {marker} — {check['prompt_text'][:80]}")
            for url in check["cited_urls"][:10]:
                self.stdout.write(f"    {url}")
            if check.get("error"):
                self.stdout.write(self.style.ERROR(f"    error: {check['error']}"))

        self.stdout.write(self.style.SUCCESS(f"\n{json.dumps(dataclasses.asdict(summary), indent=2)}"))
