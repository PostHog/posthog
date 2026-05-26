"""
Run stub training for an autoresearch pipeline.

Creates a hand-authored champion recipe and marks the pipeline as running.
Use this for local dev before the real TaskRun/agent sandbox is wired up.

Usage:
    # First create a pipeline via the API, then:
    python manage.py autoresearch_train --pipeline-id <uuid>

    # Or create one inline:
    python manage.py autoresearch_train \\
        --team-id 2 \\
        --target '$pageview' \\
        --name "My first pipeline" \\
        --horizon 7 \\
        --mode adoption \\
        --create
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.stub_training import run_stub_training


class Command(BaseCommand):
    help = "Run stub training for an autoresearch pipeline (local dev)."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", type=str, help="UUID of an existing pipeline.")
        parser.add_argument("--team-id", type=int, help="Team ID (required with --create).")
        parser.add_argument("--target", help="Target event name (required with --create).")
        parser.add_argument("--name", default="Dev pipeline", help="Pipeline name (used with --create).")
        parser.add_argument("--horizon", type=int, default=7, help="Horizon days (used with --create).")
        parser.add_argument(
            "--mode",
            default="adoption",
            choices=["adoption", "continuation"],
            help="Prediction mode (used with --create).",
        )
        parser.add_argument(
            "--create",
            action="store_true",
            help="Create a draft pipeline on the fly before training.",
        )

    def handle(self, *args, **options):
        if options["pipeline_id"]:
            try:
                pipeline = AutoresearchPipeline.objects.get(pk=options["pipeline_id"])
            except AutoresearchPipeline.DoesNotExist:
                raise CommandError(f"Pipeline {options['pipeline_id']} not found.")
        elif options["create"]:
            if not options["team_id"]:
                raise CommandError("--team-id is required with --create.")
            if not options["target"]:
                raise CommandError("--target is required with --create.")
            try:
                team = Team.objects.get(pk=options["team_id"])
            except Team.DoesNotExist:
                raise CommandError(f"Team {options['team_id']} not found.")

            safe_name = options["target"].lstrip("$").replace(" ", "_").lower()
            pipeline = AutoresearchPipeline.objects.create(
                team=team,
                name=options["name"],
                target_event=options["target"],
                target_definition={},
                horizon_days=options["horizon"],
                prediction_mode=options["mode"],
                training_population={},
                inference_population={},
                output_person_property=f"predicted_p_{safe_name}",
                status=AutoresearchPipeline.Status.DRAFT,
            )
            self.stdout.write(self.style.SUCCESS(f"Created pipeline {pipeline.pk} ({pipeline.name})"))
        else:
            raise CommandError("Provide --pipeline-id or use --create to make a new pipeline.")

        self.stdout.write(f"\nRunning stub training for pipeline '{pipeline.name}' ({pipeline.pk})")
        self.stdout.write(f"  Target   : {pipeline.target_event}")
        self.stdout.write(f"  Horizon  : {pipeline.horizon_days} days")
        self.stdout.write(f"  Mode     : {pipeline.prediction_mode}")
        self.stdout.write("")

        training_run = run_stub_training(pipeline=pipeline)

        self.stdout.write(f"Training run  : {training_run.pk}")
        self.stdout.write(f"Status        : {training_run.status}")
        self.stdout.write(f"Iterations    : {training_run.iteration_count}")
        self.stdout.write(f"Holdout AUC   : {training_run.best_holdout_score}")

        champion = (
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .order_by("-created_at")
            .first()
        )
        if champion:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Champion model : {champion.pk}"))
            self.stdout.write(f"  Recipe hash  : {champion.recipe_hash}")
            self.stdout.write(f"  Holdout AUC  : {champion.holdout_score}")
            self.stdout.write(f"  Preliminary  : {champion.is_preliminary}")
            self.stdout.write(f"\nNext step: python manage.py autoresearch_score --pipeline-id {pipeline.pk}")
