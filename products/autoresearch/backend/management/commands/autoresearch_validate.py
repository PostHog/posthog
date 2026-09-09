"""
Validate a proposed autoresearch pipeline definition against real team data.

Usage:
    python manage.py autoresearch_validate \\
        --team-id 2 \\
        --target '$pageview' \\
        --horizon 7 \\
        --user-id 1

Prints volume estimates, base rate, and any warnings, and exits nonzero when the
definition is rejected. The counts run under the given user's HogQL access control,
as the API path does for the request user.
"""

from argparse import ArgumentParser, ArgumentTypeError
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.validation import validate_pipeline_definition


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ArgumentTypeError(f"must be a positive integer, got {value}")
    return parsed


class Command(BaseCommand):
    help = "Validate a pipeline definition (volume, base rate, warnings) without creating it."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to validate against.")
        parser.add_argument("--target", required=True, help="Target event name, e.g. '$pageview'.")
        parser.add_argument("--horizon", type=_positive_int, default=7, help="Prediction horizon in days (default: 7).")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="User whose HogQL access control the counts run under. Without one HogQL fails closed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found.")

        user: User | None = None
        if options["user_id"] is not None:
            try:
                user = User.objects.get(pk=options["user_id"])
            except User.DoesNotExist:
                raise CommandError(f"User {options['user_id']} not found.")

        self.stdout.write(f"\nValidating pipeline definition for team '{team.name}' (id={team_id})")
        self.stdout.write(f"  Target event : {options['target']}")
        self.stdout.write(f"  Horizon      : {options['horizon']} days")
        self.stdout.write("")

        result = validate_pipeline_definition(
            team=team,
            target_event=options["target"],
            horizon_days=options["horizon"],
            training_lookback_days=180,
            training_population={},
            inference_population={},
            user=user,
        )

        if result.error:
            raise CommandError(f"Validation failed with error: {result.error}")

        self.stdout.write("── Volume estimates ──────────────────────────────────")
        self.stdout.write(f"  Estimated training rows : {result.estimated_training_rows}")
        self.stdout.write(f"  Positive examples       : {result.positive_count}")
        self.stdout.write(f"  Negative examples       : {result.negative_count}")
        self.stdout.write(
            f"  Base rate               : {result.base_rate:.2%}"
            if result.base_rate is not None
            else "  Base rate               : n/a"
        )
        self.stdout.write(f"  Inference population    : {result.inference_population_size}")
        self.stdout.write("")

        if result.warnings:
            self.stdout.write("── Warnings ──────────────────────────────────────────")
            for w in result.warnings:
                color = self.style.ERROR if w.severity == "error" else self.style.WARNING
                self.stdout.write(color(f"  [{w.severity.upper()}] {w.code}: {w.message}"))
            self.stdout.write("")

        if not result.can_proceed:
            raise CommandError("Validation failed. Resolve the errors above before creating the pipeline.")
        if result.requires_acknowledgement:
            self.stdout.write(self.style.WARNING("✓ Can proceed, but the warnings above need acknowledgement."))
        else:
            self.stdout.write(self.style.SUCCESS("✓ Validation passed. The pipeline can be created."))
