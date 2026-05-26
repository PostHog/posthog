"""
Run inference for an autoresearch pipeline: score the population and emit
autoresearch_prediction events into ClickHouse via capture_internal.

Usage:
    python manage.py autoresearch_score --pipeline-id <uuid>

Requires:
    - PostHog running locally (./bin/start or hogli start)
    - Demo data generated (python manage.py generate_demo_data or similar)
    - A champion model in place (run autoresearch_train first)

The events will appear in the team's events table under the event name
'autoresearch_prediction' with properties prefixed '$autoresearch_*'.
"""

from django.core.management.base import BaseCommand, CommandError

from products.autoresearch.backend.inference import _fetch_feature_rows, _score_rows, run_inference_for_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline


class Command(BaseCommand):
    help = "Score the inference population for a pipeline and emit autoresearch_prediction events."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", type=str, required=True, help="UUID of the pipeline to score.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and score users but do not emit events (useful for debugging feature SQL).",
        )

    def handle(self, *args, **options):
        try:
            pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=options["pipeline_id"])
        except AutoresearchPipeline.DoesNotExist:
            raise CommandError(f"Pipeline {options['pipeline_id']} not found.")

        champion = (
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .order_by("-created_at")
            .first()
        )
        if not champion:
            raise CommandError(f"No champion model found for pipeline {pipeline.pk}. Run autoresearch_train first.")

        self.stdout.write(f"\nRunning inference for pipeline '{pipeline.name}' ({pipeline.pk})")
        self.stdout.write(f"  Target         : {pipeline.target_event}")
        self.stdout.write(f"  Horizon        : {pipeline.horizon_days} days")
        self.stdout.write(f"  Champion model : {champion.pk}")
        self.stdout.write(f"  Holdout AUC    : {champion.holdout_score}")
        self.stdout.write(f"  Stub recipe    : {champion.model_recipe.get('stub', False)}")
        self.stdout.write(f"  Output prop    : {pipeline.output_person_property}")
        self.stdout.write("")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run mode: fetching features but not emitting events.\n"))
            rows = _fetch_feature_rows(team=pipeline.team, pipeline=pipeline, model=champion)
            self.stdout.write(f"Feature rows fetched : {len(rows)}")
            if rows:
                self.stdout.write(f"Sample columns       : {list(rows[0].keys())}")
                scored = _score_rows(feature_rows=rows, recipe=champion.model_recipe)
                scores = [r["p_y"] for r in scored]
                if scores:
                    self.stdout.write(f"Score range          : {min(scores):.4f} – {max(scores):.4f}")
                    self.stdout.write(f"Score mean           : {sum(scores) / len(scores):.4f}")
            return

        run = run_inference_for_pipeline(pipeline=pipeline, model=champion)

        self.stdout.write(f"Run ID         : {run.pk}")
        self.stdout.write(f"Status         : {run.status}")
        self.stdout.write(f"Rows scored    : {run.rows_scored}")

        if run.metrics.get("score_distribution"):
            dist = run.metrics["score_distribution"]
            self.stdout.write("\nScore distribution:")
            self.stdout.write(f"  Count : {dist.get('count')}")
            self.stdout.write(f"  Mean  : {dist.get('mean')}")
            self.stdout.write(f"  p10   : {dist.get('p10')}")
            self.stdout.write(f"  p50   : {dist.get('p50')}")
            self.stdout.write(f"  p90   : {dist.get('p90')}")

        if run.status == "completed":
            self.stdout.write(self.style.SUCCESS(f"\n✓ Emitted {run.rows_scored} autoresearch_prediction events."))
            self.stdout.write(
                f"  Query in PostHog: SELECT distinct_id, properties.$autoresearch_p_y "
                f"FROM events WHERE event = 'autoresearch_prediction' "
                f"AND properties.$autoresearch_pipeline_id = '{pipeline.pk}' ORDER BY timestamp DESC LIMIT 20"
            )
        else:
            self.stdout.write(self.style.ERROR(f"✗ Run failed: {run.error}"))
