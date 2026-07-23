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

from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from products.autoresearch.backend.artifacts import ArtifactBundle, bundle_prefix, write_bundle
from products.autoresearch.backend.inference import _fetch_feature_rows, _score_rows, run_inference_for_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline

_FIXTURE_BUNDLE_DIR = Path(__file__).resolve().parents[2] / "test_fixtures" / "bundle"


class Command(BaseCommand):
    help = "Score the inference population for a pipeline and emit autoresearch_prediction events."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", type=str, required=True, help="UUID of the pipeline to score.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and score users but do not emit events (useful for debugging feature SQL).",
        )
        parser.add_argument(
            "--seed-fixture-bundle",
            action="store_true",
            help=(
                "Upload the reference fixture bundle to object storage and create/point a champion "
                "model at it, then score via the sandbox path. For proving inference-in-sandbox locally."
            ),
        )
        parser.add_argument(
            "--prediction-date",
            type=str,
            default=None,
            help="Backfill: score as-of this past date (YYYY-MM-DD) instead of today. Features are "
            "computed as-of that date and events emitted with that date's timestamp.",
        )
        parser.add_argument(
            "--backfill-days",
            type=int,
            default=None,
            help="Backfill the last N days (one scoring run per day, ending yesterday). Useful to "
            "populate online validation without waiting a full horizon for predictions to mature.",
        )

    def handle(self, *args, **options):
        try:
            pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=options["pipeline_id"])
        except AutoresearchPipeline.DoesNotExist:
            raise CommandError(f"Pipeline {options['pipeline_id']} not found.")

        if options["seed_fixture_bundle"]:
            champion = self._seed_fixture_bundle(pipeline)
        else:
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
        if champion.artifact_prefix:
            self.stdout.write(f"  Bundle prefix  : {champion.artifact_prefix}")
        else:
            self.stdout.write(f"  Stub recipe    : {(champion.model_recipe or {}).get('stub', False)}")
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

        prediction_dates = self._resolve_prediction_dates(options)
        if len(prediction_dates) > 1:
            self.stdout.write(
                f"Backfilling {len(prediction_dates)} dates: {prediction_dates[0]} … {prediction_dates[-1]}\n"
            )

        for prediction_date in prediction_dates:
            run = run_inference_for_pipeline(pipeline=pipeline, model=champion, prediction_date=prediction_date)

            label = f"[{prediction_date}] " if len(prediction_dates) > 1 or options.get("prediction_date") else ""
            self.stdout.write(f"{label}Run ID         : {run.pk}")
            self.stdout.write(f"{label}Status         : {run.status}")
            self.stdout.write(f"{label}Rows scored    : {run.rows_scored}")

            if run.metrics.get("score_distribution"):
                dist = run.metrics["score_distribution"]
                self.stdout.write(
                    f"  dist: count={dist.get('count')} mean={dist.get('mean')} "
                    f"p10={dist.get('p10')} p50={dist.get('p50')} p90={dist.get('p90')}"
                )

            if run.status == "completed":
                self.stdout.write(self.style.SUCCESS(f"  ✓ Emitted {run.rows_scored} autoresearch_prediction events."))
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ Run failed: {run.error}"))

        self.stdout.write(
            f"\nQuery in PostHog: SELECT distinct_id, properties.$autoresearch_p_y "
            f"FROM events WHERE event = 'autoresearch_prediction' "
            f"AND properties.$autoresearch_pipeline_id = '{pipeline.pk}' ORDER BY timestamp DESC LIMIT 20"
        )

    @staticmethod
    def _resolve_prediction_dates(options: dict) -> list[date]:
        """Resolve which prediction dates to score: a backfill window, a single past date, or today."""
        if options.get("backfill_days"):
            n = options["backfill_days"]
            today = date.today()
            # Oldest first so online validation reads a chronological history.
            return [today - timedelta(days=d) for d in range(n, 0, -1)]
        if options.get("prediction_date"):
            return [date.fromisoformat(options["prediction_date"])]
        return [date.today()]

    def _seed_fixture_bundle(self, pipeline: AutoresearchPipeline) -> AutoresearchModel:
        """Upload the reference fixture bundle and point a fresh champion model at it."""
        from django.utils import timezone

        bundle = ArtifactBundle.from_dir(_FIXTURE_BUNDLE_DIR)
        now = timezone.now()

        AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).update(
            role=AutoresearchModel.Role.ARCHIVED, archived_at=now
        )

        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            recipe_hash="fixture",
            model_recipe={},
            agent_description="fixture bundle (slice 1)",
            is_preliminary=True,
            promoted_at=now,
        )
        prefix = bundle_prefix(team_id=pipeline.team_id, pipeline_id=str(pipeline.pk), training_run_id=str(model.pk))
        write_bundle(prefix, bundle)
        model.artifact_prefix = prefix
        model.save(update_fields=["artifact_prefix"])
        self.stdout.write(self.style.SUCCESS(f"Seeded fixture bundle at {prefix}"))
        return model
