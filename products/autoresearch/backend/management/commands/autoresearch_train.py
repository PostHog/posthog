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
        --user-id 1 \\
        --create
"""

import re

from django.core.management.base import BaseCommand, CommandError

from rest_framework import serializers

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.access import has_autoresearch_access
from products.autoresearch.backend.facade.api import output_person_property_taken
from products.autoresearch.backend.management.scoping import resolve_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.presentation.views.serializers import validate_event_target
from products.autoresearch.backend.training.runner import run_training
from products.autoresearch.backend.training.stub import run_stub_training

# The bounds the API applies to the same fields.
MAX_HORIZON_DAYS = 365
MAX_ITERATION_BUDGET = 500
# AutoresearchPipeline.output_person_property is a 255-character column.
MAX_OUTPUT_PROPERTY_CHARS = 255
# AutoresearchPipeline.name is a 255-character column.
MAX_NAME_CHARS = 255
# Everything the API's output-property pattern refuses.
_UNSAFE_PROPERTY_CHARS = re.compile(r"[^A-Za-z0-9_$.\-]")


class Command(BaseCommand):
    help = "Run training for an autoresearch pipeline."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument("--pipeline-id", type=str, help="UUID of an existing pipeline.")
        parser.add_argument("--team-id", type=int, help="Team ID (required with --create).")
        parser.add_argument("--target", help="Target event name (required with --create).")
        parser.add_argument("--name", default="Dev pipeline", help="Pipeline name (used with --create).")
        parser.add_argument("--horizon", type=int, default=7, help="Horizon days (used with --create).")
        source.add_argument(
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
            help="A member of the pipeline's team. Required with --create (the pipeline's creator) and for real training.",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=5,
            help="Iteration budget for the agent (default: 5).",
        )

    def handle(self, *args, **options):
        if not 1 <= options["iterations"] <= MAX_ITERATION_BUDGET:
            raise CommandError(f"--iterations must be between 1 and {MAX_ITERATION_BUDGET}.")

        if options["pipeline_id"]:
            pipeline = resolve_pipeline(options["pipeline_id"])
            if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
                raise CommandError(f"Pipeline {pipeline.pk} is archived.")
            with team_scope(pipeline.team_id):
                self._run(pipeline, options)
            return

        if options["create"]:
            options["target"] = (options["target"] or "").strip()
            options["name"] = (options["name"] or "").strip()
            if not 1 <= len(options["name"]) <= MAX_NAME_CHARS:
                raise CommandError(f"--name must be 1 to {MAX_NAME_CHARS} characters.")
            if not options["team_id"]:
                raise CommandError("--team-id is required with --create.")
            if not options["target"]:
                raise CommandError("--target is required with --create.")
            if not 1 <= options["horizon"] <= MAX_HORIZON_DAYS:
                raise CommandError(f"--horizon must be between 1 and {MAX_HORIZON_DAYS}.")
            try:
                validate_event_target(options["target"], error_key="target")
            except serializers.ValidationError as e:
                raise CommandError(str(e.detail))
            try:
                team = Team.objects.get(pk=options["team_id"])
            except Team.DoesNotExist:
                raise CommandError(f"Team {options['team_id']} not found.")

            # The creator is who every later fit and scheduled score runs as, so a pipeline
            # without one has a champion that can never be fitted.
            creator = self._team_user(team, options["user_id"])
            # Checked before the row exists, so a refused real run leaves no draft holding the output property.
            if not options["stub"]:
                self._require_flag(creator, team.id)

            safe_name = _UNSAFE_PROPERTY_CHARS.sub("_", options["target"].lstrip("$")).lower() or "target"
            suffix = f"_{options['horizon']}d"
            output_property = f"predicted_p_{safe_name}"[: MAX_OUTPUT_PROPERTY_CHARS - len(suffix)] + suffix
            # Two pipelines on one property overwrite each other's scores.
            if output_person_property_taken(team.id, output_property):
                raise CommandError(f"Output property {output_property} is taken; pass --pipeline-id to reuse it.")
            with team_scope(team.id):
                pipeline = AutoresearchPipeline.objects.create(
                    team=team,
                    created_by=creator,
                    name=options["name"],
                    target_event=options["target"],
                    target_definition={},
                    horizon_days=options["horizon"],
                    training_population={},
                    inference_population={},
                    output_person_property=output_property,
                    status=AutoresearchPipeline.Status.DRAFT,
                )
                self.stdout.write(self.style.SUCCESS(f"Created pipeline {pipeline.pk} ({pipeline.name})"))
                self._run(pipeline, options)
            return

        raise CommandError("Provide --pipeline-id or use --create to make a new pipeline.")

    def _require_flag(self, user: User, team_id: int) -> None:
        # This command skips the flag, but the sandbox agent calls the flag-gated API.
        if not has_autoresearch_access(user, team_id=team_id):
            raise CommandError(
                f"The autoresearch flag is off for team {team_id}, so the agent's API calls would be refused."
            )

    def _team_user(self, team: Team, user_id: int | None) -> User:
        if user_id is None:
            raise CommandError("--user-id is required: pass a member of the pipeline's team.")
        # The sandbox token is minted for this user on the pipeline's team, so the user must already have access to it.
        user = team.all_users_with_access().filter(pk=user_id).first()
        if user is None:
            raise CommandError(f"User {user_id} has no access to team {team.pk}. Use --user-id to pick a member.")
        return user

    def _run(self, pipeline: AutoresearchPipeline, options) -> None:
        if options["stub"]:
            self.stdout.write(f"\nRunning stub training for pipeline '{pipeline.name}' ({pipeline.pk})")
            self.stdout.write(f"  Target   : {pipeline.target_event}")
            self.stdout.write(f"  Horizon  : {pipeline.horizon_days} days")
            self.stdout.write("")

            training_run = run_stub_training(pipeline=pipeline)
        else:
            user = self._team_user(pipeline.team, options["user_id"])
            user_id = user.pk
            self._require_flag(user, pipeline.team_id)

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
