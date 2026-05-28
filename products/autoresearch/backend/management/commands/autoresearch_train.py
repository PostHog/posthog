"""
Run training for an autoresearch pipeline.

By default launches a real agent sandbox run. Use --stub for fast local dev
without Temporal/Docker (produces a hand-authored champion recipe immediately).

Usage:
    # Real agent training (requires Temporal worker + Docker):
    python manage.py autoresearch_train --pipeline-id <uuid> --user-id 1

    # Stub training (fast, no sandbox required):
    python manage.py autoresearch_train --pipeline-id <uuid> --stub

    # Create a pipeline inline:
    python manage.py autoresearch_train \\
        --team-id 2 \\
        --target '$pageview' \\
        --name "My first pipeline" \\
        --horizon 7 \\
        --create
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.stub_training import run_stub_training
from products.autoresearch.backend.training import run_training


class Command(BaseCommand):
    help = "Run training for an autoresearch pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", type=str, help="UUID of an existing pipeline.")
        parser.add_argument("--team-id", type=int, help="Team ID (required with --create).")
        parser.add_argument("--target", help="Target event name (required with --create).")
        parser.add_argument("--name", default="Dev pipeline", help="Pipeline name (used with --create).")
        parser.add_argument("--horizon", type=int, default=7, help="Horizon days (used with --create).")
        parser.add_argument(
            "--create",
            action="store_true",
            help="Create a draft pipeline on the fly before training.",
        )
        parser.add_argument(
            "--stub",
            action="store_true",
            help="Use stub training (fast, no sandbox required). Default: real agent training.",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=1,
            help="User ID for launching the real agent (default: 1).",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=5,
            help="Iteration budget for the agent (default: 5).",
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
                training_population={},
                inference_population={},
                output_person_property=f"predicted_p_{safe_name}",
                status=AutoresearchPipeline.Status.DRAFT,
            )
            self.stdout.write(self.style.SUCCESS(f"Created pipeline {pipeline.pk} ({pipeline.name})"))
        else:
            raise CommandError("Provide --pipeline-id or use --create to make a new pipeline.")

        if options["stub"]:
            self.stdout.write(f"\nRunning stub training for pipeline '{pipeline.name}' ({pipeline.pk})")
            self.stdout.write(f"  Target   : {pipeline.target_event}")
            self.stdout.write(f"  Horizon  : {pipeline.horizon_days} days")
            self.stdout.write("")

            training_run = run_stub_training(pipeline=pipeline)
        else:
            user_id = options["user_id"]
            try:
                User.objects.get(pk=user_id)
            except User.DoesNotExist:
                raise CommandError(f"User {user_id} not found. Use --user-id to specify a valid user.")

            iteration_budget = options["iterations"]
            self.stdout.write(f"\nLaunching real agent training for pipeline '{pipeline.name}' ({pipeline.pk})")
            self.stdout.write(f"  Target      : {pipeline.target_event}")
            self.stdout.write(f"  Horizon     : {pipeline.horizon_days} days")
            self.stdout.write(f"  Iterations  : {iteration_budget}")
            self.stdout.write(f"  User ID     : {user_id}")
            self.stdout.write("")

            training_run = run_training(pipeline=pipeline, iteration_budget=iteration_budget, user_id=user_id)

        self.stdout.write(f"Training run  : {training_run.pk}")
        self.stdout.write(f"Status        : {training_run.status}")

        if options["stub"]:
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
        else:
            task_run_id = training_run.task_run_id
            self.stdout.write(f"Task run      : {task_run_id}")
            self.stdout.write("")
            self.stdout.write("Agent is running in the background. Monitor progress:")
            self.stdout.write(f"  tail -f /tmp/temporal-worker2.log | grep {str(training_run.pk)[:8]}")
            self.stdout.write("")
            self.stdout.write("Check training run status:")
            self.stdout.write(
                f"  python manage.py shell -c \"from products.autoresearch.backend.models import AutoresearchTrainingRun; r = AutoresearchTrainingRun.objects.get(pk='{training_run.pk}'); print(r.status, r.error)\""
            )

        self.stdout.write(f"\nNext step: python manage.py autoresearch_score --pipeline-id {pipeline.pk}")
