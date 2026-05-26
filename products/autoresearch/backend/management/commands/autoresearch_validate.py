"""
Validate a proposed autoresearch pipeline definition against real team data.

Usage:
    python manage.py autoresearch_validate \\
        --team-id 2 \\
        --target '$pageview' \\
        --horizon 7 \\
        --mode adoption

Prints volume estimates, base rate, and any warnings.
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team

from products.autoresearch.backend.validation import validate_pipeline_definition


class Command(BaseCommand):
    help = "Validate a pipeline definition (volume, base rate, warnings) without creating it."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to validate against.")
        parser.add_argument("--target", required=True, help="Target event name, e.g. '$pageview'.")
        parser.add_argument("--horizon", type=int, default=7, help="Prediction horizon in days (default: 7).")
        parser.add_argument(
            "--mode",
            default="adoption",
            choices=["adoption", "continuation"],
            help="Prediction mode: 'adoption' (first-time) or 'continuation' (repeat). Default: adoption.",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found.")

        self.stdout.write(f"\nValidating pipeline definition for team '{team.name}' (id={team_id})")
        self.stdout.write(f"  Target event : {options['target']}")
        self.stdout.write(f"  Horizon      : {options['horizon']} days")
        self.stdout.write(f"  Mode         : {options['mode']}")
        self.stdout.write("")

        result = validate_pipeline_definition(
            team=team,
            target_event=options["target"],
            horizon_days=options["horizon"],
            prediction_mode=options["mode"],
            training_population={},
            inference_population={},
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

        if result.can_proceed:
            if result.requires_acknowledgement:
                self.stdout.write(self.style.WARNING("✓ Can proceed — but warnings require acknowledgement."))
            else:
                self.stdout.write(self.style.SUCCESS("✓ Validation passed — pipeline can be created."))
        else:
            self.stdout.write(self.style.ERROR("✗ Validation failed — resolve errors before creating the pipeline."))
