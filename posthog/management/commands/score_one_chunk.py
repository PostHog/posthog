"""Manual smoke-test for the session surfacing scoring pipeline.

Pulls one bucket of unscored sessions from ClickHouse, runs the XGBoost
booster against them, and prints the resulting scores. Does NOT write
anything back — read-only.

Requires `SESSION_INTERESTINGNESS_MODEL_S3_URI` to be set
(see surfacing_scoring_sweep README).

Use cases:
    * Verify the model loads and predicts in a fresh dev / staging environment
      without having to schedule the Temporal workflow.
    * Eyeball the score distribution against real data shapes when iterating
      on a retrained model.
    * Reproduce a prod scoring failure locally with the same SQL the activity
      runs.

Examples:
    ./bin/python manage.py score_one_chunk
    ./bin/python manage.py score_one_chunk --chunk-size 50 --lookback-days 30
    ./bin/python manage.py score_one_chunk --chunk-id 7 --of-chunks 20

The defaults match the pipeline's tick budget (`chunk_size=10`,
`of_chunks=1`) but small enough that you can read the output. Production
runs use `chunk_size=10_000` and `of_chunks=20`.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import _fetch_features_dataframe
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FeatureValidationError, validate_features
from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import get_feature_names, predict
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import ChunkSpec


class Command(BaseCommand):
    help = "Score one chunk of unscored sessions and print the results (no writeback)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--chunk-id",
            type=int,
            default=0,
            help="Hash bucket id; must be < --of-chunks. Defaults to 0.",
        )
        parser.add_argument(
            "--of-chunks",
            type=int,
            default=1,
            help="Total number of hash buckets. Defaults to 1 (every session in this bucket).",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=10,
            help="Max rows to fetch + score. Defaults to 10 for legible output.",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=7,
            help="Only consider sessions newer than this many days. Defaults to 7 (matches prod).",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        spec = ChunkSpec(
            chunk_id=options["chunk_id"],
            of_chunks=options["of_chunks"],
            chunk_size=options["chunk_size"],
            lookback_days=options["lookback_days"],
        )

        self.stdout.write(self.style.NOTICE(f"Fetching with {spec} ..."))
        df = _fetch_features_dataframe(spec)
        self.stdout.write(f"  rows={len(df)} cols={len(df.columns)}")
        if df.empty:
            self.stdout.write(self.style.WARNING("No unscored sessions in this bucket — nothing to score."))
            return

        feature_names = get_feature_names()
        self.stdout.write(f"  booster.feature_names: {len(feature_names)} features")

        try:
            validate_features(df, feature_names=feature_names)
        except FeatureValidationError as e:
            self.stdout.write(
                self.style.ERROR(
                    f"validate_features failed: {e}\n"
                    "  → SQL output drifted from the booster's expected schema. "
                    "Run `pytest posthog/temporal/tests/session_replay/surfacing_scoring_sweep/test_sql_alignment.py` "
                    "to localize the mismatch."
                )
            )
            return

        scores = predict(df)
        self.stdout.write(self.style.SUCCESS(f"Scored {len(scores)} session(s):"))
        for session_id, team_id, score in zip(df["session_id"], df["team_id"], scores, strict=True):
            self.stdout.write(f"  team={team_id}  session={session_id}  score={float(score):.4f}")

        self.stdout.write("")
        self.stdout.write(
            f"  min={float(scores.min()):.4f}  max={float(scores.max()):.4f}  mean={float(scores.mean()):.4f}"
        )
