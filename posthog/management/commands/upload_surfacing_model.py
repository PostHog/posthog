"""Upload a trained XGBoost booster (.ubj) to object storage.

Uses `posthog.storage.object_storage` so it works against prod S3, staging, and
local object storage with no config changes. After upload, set on the worker:
    SESSION_SURFACING_MODEL_S3_URI=s3://<bucket>/<key>

Examples:
    ./bin/python manage.py upload_surfacing_model ./surfacing_score_xgb_v1.ubj
    ./bin/python manage.py upload_surfacing_model ./surfacing_score_xgb_v1.ubj --bucket my-bucket --key surfacing-scoring/surfacing_score_xgb_v2.ubj
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import xgboost as xgb

from posthog.storage import object_storage
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import MODEL_S3_KEY
from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import (
    FeatureSchemaDriftError,
    assert_serving_schema_parity,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import MissingFeatureRangeError


class Command(BaseCommand):
    help = "Upload a session surfacing booster (.ubj) to object storage."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path",
            type=str,
            help="Local path to the .ubj booster file to upload.",
        )
        parser.add_argument(
            "--bucket",
            type=str,
            default=None,
            help=f"Target bucket. Defaults to settings.OBJECT_STORAGE_BUCKET ({settings.OBJECT_STORAGE_BUCKET!r}).",
        )
        parser.add_argument(
            "--key",
            type=str,
            default=MODEL_S3_KEY,
            help=f"Object key. Defaults to {MODEL_S3_KEY!r}.",
        )
        parser.add_argument(
            "--skip-validate",
            action="store_true",
            help="Skip xgb.Booster.load_model() round-trip + feature_names check.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        source = Path(options["path"])
        if not source.is_file():
            raise CommandError(f"Source file {source!r} does not exist or is not a regular file.")

        if not options["skip_validate"]:
            try:
                booster = xgb.Booster()
                booster.load_model(str(source))
            except Exception as e:
                raise CommandError(f"xgboost rejected {source!r}: {e}")
            names = tuple(booster.feature_names or ())
            if not names:
                raise CommandError(
                    f"{source!r} has no feature_names. Pass `feature_names=` to xgb.DMatrix at train time."
                )
            try:
                assert_serving_schema_parity(names)
            except (FeatureSchemaDriftError, MissingFeatureRangeError) as e:
                raise CommandError(f"booster doesn't match current SQL/FEATURE_RANGES:\n{e}")
            self.stdout.write(f"  validated: {len(names)} features, {source.stat().st_size} bytes")

        bucket = options["bucket"] or settings.OBJECT_STORAGE_BUCKET
        key = options["key"]
        self.stdout.write(self.style.NOTICE(f"Uploading {source} → s3://{bucket}/{key} ..."))

        object_storage.write_from_file(file_name=key, file_path=str(source), bucket=bucket)

        self.stdout.write(self.style.SUCCESS(f"Uploaded. Wire on the worker:"))
        self.stdout.write(f"  SESSION_SURFACING_MODEL_S3_URI=s3://{bucket}/{key}")
