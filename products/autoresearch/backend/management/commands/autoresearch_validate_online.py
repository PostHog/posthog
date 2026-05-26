"""
Run online validation for an autoresearch pipeline.

Finds all matured, unvalidated prediction dates (today >= prediction_date + horizon_days),
joins them to realized target outcomes, and computes realized AUC / Brier / ECE / lift@k
per model. Updates AutoresearchModel.realized_score and calibration_error in Postgres.

Usage:
    python manage.py autoresearch_validate_online --pipeline-id <uuid>
    python manage.py autoresearch_validate_online --pipeline-id <uuid> --dry-run

Requires:
    - PostHog running locally (./bin/start or hogli start)
    - autoresearch_prediction events in ClickHouse (run autoresearch_score first)
    - Enough time elapsed for the horizon to close (horizon_days must have passed)
"""

from django.core.management.base import BaseCommand, CommandError

from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.online_validation import (
    _fetch_matured_prediction_dates,
    _find_mature_unvalidated_dates,
    run_online_validation_for_pipeline,
)


class Command(BaseCommand):
    help = "Run online validation for a pipeline: join predictions to realized labels and update model metrics."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument("--pipeline-id", type=str, required=True, help="UUID of the pipeline to validate.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show matured dates and skip DB writes.",
        )

    def handle(self, *args: object, **options: object) -> None:
        try:
            pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=options["pipeline_id"])
        except AutoresearchPipeline.DoesNotExist:
            raise CommandError(f"Pipeline {options['pipeline_id']} not found.")

        self.stdout.write(f"\nPipeline  : {pipeline.name} ({pipeline.pk})")
        self.stdout.write(f"Target    : {pipeline.target_event}")
        self.stdout.write(f"Horizon   : {pipeline.horizon_days} days")
        self.stdout.write("")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run mode: showing matured dates but not running validation.\n"))
            all_matured = _fetch_matured_prediction_dates(team=pipeline.team, pipeline=pipeline)
            unvalidated = _find_mature_unvalidated_dates(team=pipeline.team, pipeline=pipeline)
            validated = [d for d in all_matured if d not in unvalidated]
            self.stdout.write(f"Matured dates     : {len(all_matured)}")
            self.stdout.write(f"Already validated : {len(validated)}")
            self.stdout.write(f"Pending           : {len(unvalidated)}")
            if unvalidated:
                for d in sorted(unvalidated):
                    self.stdout.write(f"  {d.isoformat()}")
            return

        runs = run_online_validation_for_pipeline(pipeline=pipeline)

        if not runs:
            self.stdout.write(self.style.WARNING("No matured, unvalidated prediction dates found."))
            self.stdout.write("Either no predictions have been scored yet, or all mature dates are already validated.")
            return

        self.stdout.write(f"Validated {len(runs)} prediction date(s):\n")
        for run in runs:
            prediction_date = run.metrics.get("prediction_date", "?")
            status = run.status
            n_labels = run.metrics.get("realized_labels_count", "?")
            self.stdout.write(
                f"  {prediction_date}  status={status}  rows_scored={run.rows_scored}  realized_labels={n_labels}"
            )

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

        completed = [r for r in runs if r.status == "completed"]
        if completed:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Completed validation for {len(completed)} date(s)."))
        failed = [r for r in runs if r.status == "failed"]
        if failed:
            self.stdout.write(self.style.ERROR(f"✗ {len(failed)} validation run(s) failed."))
