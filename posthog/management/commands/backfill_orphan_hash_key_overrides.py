"""Backfill management command — sweep orphan ``FeatureFlagHashKeyOverride`` rows.

Companion to PR #56521 (write-time cleanup hooks). The hooks only fire on
product-driven paths (PATCH rename, PATCH soft-delete) on flags whose row
count for the affected (team, key) tuple is below the inline threshold.
This command is the safety net for everything else:

1. Orphans accumulated *before* the write-time hooks shipped.
2. Cases the hooks intentionally skipped because the team's row count
   exceeded ``HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD`` (50_000).
3. Hard-delete paths (admin tooling) that bypass the serializer entirely.

An orphan row is a ``FeatureFlagHashKeyOverride`` whose
``(team_id, feature_flag_key)`` tuple does not match any current flag key
in that team — including soft-deleted flags' current (suffixed) keys.

Usage examples::

    # Dry-run across all teams; reports counts only.
    python manage.py backfill_orphan_hash_key_overrides --dry-run

    # Real run, one team at a time, with throttling.
    python manage.py backfill_orphan_hash_key_overrides \\
        --team-id 12345 \\
        --batch-size 5000 \\
        --sleep-between-batches 0.5

    # Bound the run for an operator who wants to ship a partial sweep.
    python manage.py backfill_orphan_hash_key_overrides --max-batches 20
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

import structlog

from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.models.team import Team
from posthog.person_db_router import PERSONS_DB_FOR_WRITE

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 10_000
DEFAULT_SLEEP_BETWEEN_BATCHES = 0.5


class Command(BaseCommand):
    help = "Sweep orphan FeatureFlagHashKeyOverride rows whose feature_flag_key no longer matches any flag in the team."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Walk the orphan rows without deleting them and log the count per batch. "
                "Bounded by --max-batches when set; otherwise scans every orphan in the "
                "selected team(s) using an id-cursor window."
            ),
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Restrict the sweep to a single team. Omit to iterate all teams.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows deleted per atomic block (default {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--sleep-between-batches",
            type=float,
            default=DEFAULT_SLEEP_BETWEEN_BATCHES,
            help=f"Seconds to sleep between batches to throttle write load (default {DEFAULT_SLEEP_BETWEEN_BATCHES}).",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help="Cap the total number of batches across all teams. Omit for unbounded.",
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run: bool = bool(options["dry_run"])
        team_id: int | None = options["team_id"]  # type: ignore[assignment]
        batch_size: int = int(options["batch_size"])  # type: ignore[arg-type]
        sleep_between_batches: float = float(options["sleep_between_batches"])  # type: ignore[arg-type]
        max_batches: int | None = options["max_batches"]  # type: ignore[assignment]

        if batch_size <= 0:
            raise ValueError("--batch-size must be positive")

        team_ids = [team_id] if team_id is not None else list(Team.objects.order_by("id").values_list("id", flat=True))
        logger.info(
            "backfill_orphan_hash_key_overrides_start",
            dry_run=dry_run,
            team_count=len(team_ids),
            batch_size=batch_size,
            sleep_between_batches=sleep_between_batches,
            max_batches=max_batches,
        )

        total_orphans_seen = 0
        total_deleted = 0
        batches_run = 0
        teams_processed = 0

        for current_team_id in team_ids:
            if max_batches is not None and batches_run >= max_batches:
                logger.info("backfill_orphan_hash_key_overrides_max_batches_reached", batches_run=batches_run)
                break

            # ``objects_including_soft_deleted`` returns the current key for
            # every flag in the team, including those whose key was suffixed
            # with ``:deleted:<id>`` during soft-delete. Override rows whose
            # key is not in this set are orphans.
            keys_to_keep = list(
                FeatureFlag.objects_including_soft_deleted.filter(team_id=current_team_id).values_list("key", flat=True)
            )

            team_orphans, team_deleted, team_batches = self._sweep_team(
                team_id=current_team_id,
                keys_to_keep=keys_to_keep,
                batch_size=batch_size,
                sleep_between_batches=sleep_between_batches,
                dry_run=dry_run,
                remaining_batches=(max_batches - batches_run) if max_batches is not None else None,
            )
            total_orphans_seen += team_orphans
            total_deleted += team_deleted
            batches_run += team_batches
            teams_processed += 1

        logger.info(
            "backfill_orphan_hash_key_overrides_complete",
            dry_run=dry_run,
            teams_processed=teams_processed,
            teams_total=len(team_ids),
            orphans_seen=total_orphans_seen,
            rows_deleted=total_deleted,
            batches_run=batches_run,
        )

    def _sweep_team(
        self,
        *,
        team_id: int,
        keys_to_keep: list[str],
        batch_size: int,
        sleep_between_batches: float,
        dry_run: bool,
        remaining_batches: int | None,
    ) -> tuple[int, int, int]:
        """Process one team's orphans. Returns (orphans_seen, rows_deleted, batches_run).

        Uses an id-cursor window (``id__gt=last_seen_id``) so dry-run mode can
        walk the full orphan set without re-selecting the same rows forever
        (deletion-based windowing isn't available when nothing is being
        deleted). Real runs benefit too — the cursor shape is the same in
        both modes, and ``id__gt`` plays well with the ``(id)`` primary-key
        index.
        """
        orphans_seen = 0
        rows_deleted = 0
        batches_run = 0
        last_seen_id = 0

        while True:
            if remaining_batches is not None and batches_run >= remaining_batches:
                break

            ids_qs = (
                FeatureFlagHashKeyOverride.objects.using(PERSONS_DB_FOR_WRITE)
                .filter(team_id=team_id, id__gt=last_seen_id)
                .exclude(feature_flag_key__in=keys_to_keep)
                .order_by("id")
                .values_list("id", flat=True)[:batch_size]
            )
            ids = list(ids_qs)
            if not ids:
                break

            orphans_seen += len(ids)
            batches_run += 1
            last_seen_id = ids[-1]

            if dry_run:
                logger.info(
                    "backfill_orphan_hash_key_overrides_dry_run_batch",
                    team_id=team_id,
                    batch_size=len(ids),
                    batches_run_for_team=batches_run,
                    cursor=last_seen_id,
                )
            else:
                with transaction.atomic(using=PERSONS_DB_FOR_WRITE):
                    deleted, _ = (
                        FeatureFlagHashKeyOverride.objects.using(PERSONS_DB_FOR_WRITE).filter(id__in=ids).delete()
                    )
                    rows_deleted += deleted
                logger.info(
                    "backfill_orphan_hash_key_overrides_batch",
                    team_id=team_id,
                    rows_deleted=deleted,
                    batches_run_for_team=batches_run,
                )

            if sleep_between_batches > 0:
                time.sleep(sleep_between_batches)

        return orphans_seen, rows_deleted, batches_run
