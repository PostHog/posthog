"""
Run online validation for an autoresearch pipeline.

Finds the matured prediction dates that have no completed validation, joins their
predictions to realized target outcomes, and computes realized AUC / Brier / ECE / lift@k
per model. Updates AutoresearchModel.realized_score and calibration_error in Postgres.

Usage:
    python manage.py autoresearch_validate_online --pipeline-id <uuid>
    python manage.py autoresearch_validate_online --pipeline-id <uuid> --dry-run

Requires:
    - PostHog running locally (./bin/start or hogli start)
    - completed inference runs whose predictions are in ClickHouse (run autoresearch_score first)
    - Enough time elapsed for the horizon to close (horizon_days must have passed)
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.autoresearch.backend.evaluation.online_validation import (
    find_pending_validation_dates,
    run_online_validation_for_pipeline,
)
from products.autoresearch.backend.management.scoping import resolve_pipeline
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchRun


class Command(BaseCommand):
    help = "Run online validation for a pipeline: join predictions to realized labels and update model metrics."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--pipeline-id", type=str, required=True, help="UUID of the pipeline to validate.")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="Run the queries as this user. Defaults to the pipeline's creator.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the matured dates waiting for validation and skip DB writes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        pipeline = resolve_pipeline(options["pipeline_id"])
        user = self._resolve_user(options["user_id"])
        with team_scope(pipeline.team_id):
            self._run(pipeline, user, options)

    @staticmethod
    def _resolve_user(user_id: int | None) -> User | None:
        if user_id is None:
            return None
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise CommandError(f"User {user_id} not found.")

    def _run(self, pipeline: AutoresearchPipeline, user: User | None, options: dict[str, Any]) -> None:
        self.stdout.write(f"\nPipeline  : {pipeline.name} ({pipeline.pk})")
        self.stdout.write(f"Target    : {pipeline.target_event}")
        self.stdout.write(f"Horizon   : {pipeline.horizon_days} days")
        self.stdout.write("")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run mode: showing the pending dates but not validating them.\n"))
            pending = find_pending_validation_dates(pipeline)
            self.stdout.write(f"Pending dates : {len(pending)}")
            for item in pending:
                models = ", ".join(
                    f"{model_id[:8]}… ({rows} rows)" for model_id, rows in item.expected_rows_by_model.items()
                )
                self.stdout.write(f"  {item.prediction_date.isoformat()}  horizon={item.horizon_days}d  {models}")
            return

        runs = run_online_validation_for_pipeline(pipeline, user=user)

        if not runs:
            self.stdout.write(self.style.WARNING("No matured prediction dates are waiting for validation."))
            self.stdout.write(
                "Either no completed scoring run has passed its horizon yet, or every matured date is already validated."
            )
            return

        self.stdout.write(f"Validated {len(runs)} prediction date(s):\n")
        for run in runs:
            prediction_date = run.metrics.get("prediction_date", "?")
            n_labels = run.metrics.get("realized_labels_count", "?")
            self.stdout.write(
                f"  {prediction_date}  status={run.status}  rows_scored={run.rows_scored}  realized_labels={n_labels}"
            )
            if run.error:
                self.stdout.write(f"    error: {run.error}")

            per_model = run.metrics.get("per_model", {})
            for model_id, m in per_model.items():
                auc = m.get("realized_auc")
                brier = m.get("brier_score")
                ece = m.get("calibration_error")
                lift10 = m.get("lift_at_10")
                role = m.get("model_role", "?")
                self.stdout.write(
                    f"    Model {model_id[:8]}…  role={role}  AUC={auc}  Brier={brier}  ECE={ece}  lift@10={lift10}"
                )

        completed = [r for r in runs if r.status == AutoresearchRun.Status.COMPLETED]
        if completed:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Completed validation for {len(completed)} date(s)."))
        failed = [r for r in runs if r.status == AutoresearchRun.Status.FAILED]
        if failed:
            raise CommandError(
                f"{len(failed)} validation run(s) failed. Each failed date is retried on the next pass; "
                "the run's error field says why."
            )
