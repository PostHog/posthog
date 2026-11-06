"""Run the eval suggestions pipeline for one team, synchronously, and print what it published.

Usage:
    python manage.py run_eval_suggestions --team-id 4201
    python manage.py run_eval_suggestions --team-id 4201 --include-paid
"""

import json

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from products.ai_observability.backend.eval_suggestions.config import load_settings
from products.ai_observability.backend.eval_suggestions.pipeline import create_run, execute_run
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionRun,
    EvalSuggestionRunTrigger,
)


class Command(BaseCommand):
    help = "Run the eval suggestions pipeline for one team and print the suggestions it publishes"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--include-paid",
            action="store_true",
            help="Also run decision-model screening and, when the flag payload allows it, paid drafting",
        )

    def handle(self, *args: object, **options: object) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} does not exist")
        run = create_run(team, EvalSuggestionRunTrigger.MANUAL)
        execute_run(str(run.id), include_paid=bool(options["include_paid"]), settings=load_settings())
        run = EvalSuggestionRun.objects.for_team(team.pk).get(id=run.id)
        self.stdout.write(json.dumps(run.stages, indent=2, default=str))
        for suggestion in EvalSuggestion.objects.for_team(team.pk).filter(run=run).order_by("-score"):
            rate = (
                f"{suggestion.measured_failure_rate:.1%} of {suggestion.sample_size}"
                if suggestion.measured_failure_rate is not None
                else "possible"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[{suggestion.kind}] {suggestion.headline} ({rate}, score {suggestion.score:.2f})"
                )
            )
            self.stdout.write(f"  {suggestion.outcome}")
            self.stdout.write(f"  {suggestion.reason}")
            if suggestion.filters:
                self.stdout.write(
                    f"  filters: {json.dumps(suggestion.filters)}  rollout: {suggestion.rollout_percentage}%"
                )
            for evidence in suggestion.evidence:
                self.stdout.write(f"  trace {evidence['trace_id']}: {evidence['reason']}")
        self.stdout.write(f"\nRun {run.id}: {run.status}")
