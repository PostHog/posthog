import json
import dataclasses
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.engines import (
    ClaudeWebSearchEngine,
    ExaAnswerEngine,
    GeminiGroundedEngine,
    OpenAIWebSearchEngine,
)
from products.aeo.backend.runner import run_citation_checks

ENGINES_BY_NAME = {
    "claude": ClaudeWebSearchEngine,
    "openai": OpenAIWebSearchEngine,
    "exa": ExaAnswerEngine,
    "gemini": GeminiGroundedEngine,
}


class Command(BaseCommand):
    help = (
        "Run AEO citation checks for a team. "
        "Smoke test (runs engines, records nothing): --limit 3 --dry-run. "
        "Note: engines make real, billed API calls even with --dry-run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--limit", type=int, help="Max prompts this run (default 50).")
        parser.add_argument(
            "--engines",
            type=str,
            help="Comma-separated subset of: claude,openai,exa,gemini. Default: all configured (gemini only with its flag).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Run engines but record no checks.")
        parser.add_argument(
            "--allow-ungated-gemini",
            action="store_true",
            help=(
                "Record gemini checks without the aeo-engine-gemini flag. The flag holds the engine "
                "until a review of Google's grounding terms clears it, so without this option a run "
                "that includes gemini must be a --dry-run."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        engine_names = [name.strip() for name in options["engines"].split(",")] if options["engines"] else []
        for name in engine_names:
            if name not in ENGINES_BY_NAME:
                raise CommandError(f"Unknown engine '{name}'. Choose from {sorted(ENGINES_BY_NAME)}")
        if "gemini" in engine_names and not options["dry_run"] and not options["allow_ungated_gemini"]:
            raise CommandError(
                "A run that includes gemini records checks only with --allow-ungated-gemini. "
                "Pass --dry-run to run it without recording."
            )

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")

        engines = [ENGINES_BY_NAME[name]() for name in engine_names] or None

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

        self.stdout.write(self.style.SUCCESS(f"\n{json.dumps(dataclasses.asdict(summary), indent=2)}"))
