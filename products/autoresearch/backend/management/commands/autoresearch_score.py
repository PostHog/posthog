"""
Run inference for an autoresearch pipeline: score the population and emit
autoresearch_prediction events through capture.

Usage:
    python manage.py autoresearch_score --pipeline-id <uuid>

Requires:
    - PostHog running locally (./bin/start or hogli start)
    - Demo data generated (python manage.py generate_demo_data or similar)
    - A champion model in place (run autoresearch_train first)

The events appear in the team's events table under the event name
'autoresearch_prediction' with properties prefixed '$autoresearch_*'.
"""

from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.autoresearch.backend.inference.sandbox import fit_champion_model
from products.autoresearch.backend.inference.scoring import (
    ScoredPopulation,
    ScoringWindow,
    _summarize_scores,
    run_inference_for_pipeline,
    score_population,
)
from products.autoresearch.backend.management.scoping import resolve_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.training.artifacts import ArtifactBundle, bundle_prefix, write_bundle

_FIXTURE_BUNDLE_DIR = Path(__file__).resolve().parents[2] / "test_fixtures" / "bundle"


class Command(BaseCommand):
    help = "Score the inference population for a pipeline and emit autoresearch_prediction events."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", type=str, required=True, help="UUID of the pipeline to score.")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="Run the queries as this user. Defaults to the pipeline's creator.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Score the population through the champion's normal path but do not emit events.",
        )
        parser.add_argument(
            "--seed-fixture-bundle",
            action="store_true",
            help=(
                "Upload the reference fixture bundle to object storage and create/point a champion "
                "model at it, then score via the sandbox path. For proving inference-in-sandbox locally."
            ),
        )
        dates = parser.add_mutually_exclusive_group()
        dates.add_argument(
            "--prediction-date",
            type=str,
            default=None,
            help="Backfill: score as of this past date (YYYY-MM-DD) instead of today. Features are "
            "computed as of that date and events are emitted with that date's timestamp.",
        )
        dates.add_argument(
            "--backfill-days",
            type=int,
            default=None,
            help="Backfill the last N days (one scoring run per day, ending yesterday). Useful to "
            "populate online validation without waiting a full horizon for predictions to mature.",
        )

    def handle(self, *args, **options):
        pipeline = resolve_pipeline(options["pipeline_id"])
        user = self._resolve_user(options["user_id"])
        prediction_dates = self._resolve_prediction_dates(options)
        with team_scope(pipeline.team_id):
            self._run(pipeline, user, prediction_dates, options)

    @staticmethod
    def _resolve_user(user_id: int | None) -> User | None:
        if user_id is None:
            return None
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise CommandError(f"User {user_id} not found.")

    def _run(self, pipeline: AutoresearchPipeline, user: User | None, prediction_dates: list[date], options):
        champion: AutoresearchModel | None
        if options["seed_fixture_bundle"]:
            champion = self._seed_fixture_bundle(pipeline, user)
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

        if len(prediction_dates) > 1:
            self.stdout.write(
                f"Backfilling {len(prediction_dates)} dates: {prediction_dates[0]} to {prediction_dates[-1]}\n"
            )
        labelled = len(prediction_dates) > 1 or options.get("prediction_date")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: scoring through the champion's path, not emitting.\n"))
            for prediction_date in prediction_dates:
                scored = score_population(
                    team=pipeline.team,
                    pipeline=pipeline,
                    model=champion,
                    window=ScoringWindow.for_date(prediction_date),
                    user=user,
                )
                self._print_scores(scored, label=f"[{prediction_date}] " if labelled else "")
            return

        for prediction_date in prediction_dates:
            run = run_inference_for_pipeline(
                pipeline=pipeline, model=champion, prediction_date=prediction_date, user=user
            )
            label = f"[{prediction_date}] " if labelled else ""
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
                self.stdout.write(self.style.SUCCESS(f"  Emitted {run.rows_scored} autoresearch_prediction events."))
            else:
                self.stdout.write(self.style.ERROR(f"  Run failed: {run.error}"))

        self.stdout.write(
            f"\nQuery in PostHog: SELECT distinct_id, properties.$autoresearch_p_y "
            f"FROM events WHERE event = 'autoresearch_prediction' "
            f"AND properties.$autoresearch_pipeline_id = '{pipeline.pk}' ORDER BY timestamp DESC LIMIT 20"
        )

    def _print_scores(self, scored: ScoredPopulation, *, label: str) -> None:
        self.stdout.write(f"{label}Rows scored    : {len(scored.rows)}")
        if not scored.rows:
            return
        self.stdout.write(f"{label}Columns        : {[k for k in scored.rows[0].keys() if k != 'p_y']}")
        dist = _summarize_scores([row["p_y"] for row in scored.rows])
        self.stdout.write(
            f"{label}Scores         : min={dist['min']} p50={dist['p50']} max={dist['max']} mean={dist['mean']}"
        )
        if scored.holdout_auc is not None:
            self.stdout.write(f"{label}Holdout AUC    : {scored.holdout_auc}")

    @staticmethod
    def _resolve_prediction_dates(options: dict) -> list[date]:
        """The dates to score: a backfill window ending yesterday, one past date, or today."""
        today = date.today()
        backfill_days = options.get("backfill_days")
        if backfill_days is not None:
            if backfill_days < 1:
                raise CommandError("--backfill-days must be at least 1.")
            # Oldest first so online validation reads a chronological history.
            return [today - timedelta(days=d) for d in range(backfill_days, 0, -1)]
        raw_date = options.get("prediction_date")
        if raw_date:
            try:
                prediction_date = date.fromisoformat(raw_date)
            except ValueError:
                raise CommandError(f"--prediction-date must be YYYY-MM-DD, got {raw_date!r}.")
            if prediction_date > today:
                raise CommandError(f"--prediction-date {prediction_date} is in the future; scoring runs as of today.")
            return [prediction_date]
        return [today]

    def _seed_fixture_bundle(self, pipeline: AutoresearchPipeline, user: User | None) -> AutoresearchModel:
        """Upload the reference fixture bundle, fit it, and make a fresh model pointing at it the champion."""
        bundle = ArtifactBundle.from_dir(_FIXTURE_BUNDLE_DIR)
        # The upload and the fit happen before any champion is archived, so a storage or
        # sandbox failure leaves the pipeline with the champion it had. Scoring loads the
        # persisted model.pkl and never fits, so an unfitted bundle would fail every cadence.
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHALLENGER,
            recipe_hash="fixture",
            model_recipe={},
            agent_description="fixture bundle (slice 1)",
            is_preliminary=True,
        )
        prefix = bundle_prefix(team_id=pipeline.team_id, pipeline_id=str(pipeline.pk), training_run_id=str(model.pk))
        write_bundle(prefix, bundle)
        metrics = fit_champion_model(team=pipeline.team, pipeline=pipeline, prefix=prefix, bundle=bundle, user=user)
        model.holdout_score = metrics.get("holdout_auc")
        model.metrics = metrics
        now = timezone.now()
        with transaction.atomic():
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).update(
                role=AutoresearchModel.Role.ARCHIVED, archived_at=now
            )
            model.role = AutoresearchModel.Role.CHAMPION
            model.artifact_prefix = prefix
            model.promoted_at = now
            model.save(update_fields=["role", "artifact_prefix", "promoted_at", "holdout_score", "metrics"])
        self.stdout.write(self.style.SUCCESS(f"Seeded and fitted the fixture bundle at {prefix}"))
        return model
