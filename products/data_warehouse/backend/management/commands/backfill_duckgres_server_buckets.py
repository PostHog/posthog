"""Backfill DuckgresServer.bucket from the duckgres control plane's authoritative name.

Older DuckgresServer rows were created before the control plane returned the per-org
bucket name in its provision response (PostHog/duckgres#799), so their ``bucket`` is
NULL — or, worse, was populated from the local ``derive_duckling_bucket`` twin, which
has drifted from the Crossplane composition's naming (UUID hyphen-compaction + the
``mw-`` env suffix) and points at a bucket that doesn't exist.

This command reconciles each row against the single source of truth: the control
plane's ``/warehouse/status`` endpoint, which returns the exact bucket name the CP
provisioned (and pinned on the Duckling CR's ``spec.dataStore.bucketName``). It never
re-derives — a mismatch is corrected to whatever the CP reports.

Idempotent: re-running is a no-op once every row already matches its CP-reported name.
Best-effort per row: an org whose status call fails (flag off, not provisioned, CP
unreachable) is logged and skipped, never aborting the batch.

Usage:
    # Dry-run (default) — reports what would change, writes nothing
    python manage.py backfill_duckgres_server_buckets

    # Live run
    python manage.py backfill_duckgres_server_buckets --live-run

    # Restrict to one org
    python manage.py backfill_duckgres_server_buckets --live-run --organization-id <uuid>
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.ducklake.models import DuckgresServer

from products.data_warehouse.backend.api import managed_warehouse

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill DuckgresServer.bucket from the control plane's authoritative warehouse status"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Persist changes. Without this flag the command only reports (dry-run).",
        )
        parser.add_argument(
            "--organization-id",
            type=str,
            default=None,
            help="Restrict to a single organization id.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live_run"]
        org_filter: str | None = options["organization_id"]

        qs = DuckgresServer.objects.all().order_by("created_at")
        if org_filter:
            qs = qs.filter(organization_id=org_filter)

        total = qs.count()
        self.stdout.write(f"Scanning {total} DuckgresServer row(s){' (LIVE)' if live else ' (dry-run)'}")

        updated = skipped = unchanged = 0

        for server in qs.iterator():
            org_id = str(server.organization_id)

            try:
                resp = managed_warehouse.status_for(org_id)
            except Exception as exc:
                skipped += 1
                self.stderr.write(f"  {org_id}: status call raised ({exc}); skip")
                continue

            if resp.status_code != 200 or not isinstance(resp.data, dict):
                skipped += 1
                self.stderr.write(f"  {org_id}: status HTTP {resp.status_code}; skip")
                continue

            bucket = resp.data.get("bucket")
            if not bucket:
                # External data stores and not-yet-backfilled ducklings report no
                # bucket — nothing authoritative to copy.
                skipped += 1
                self.stdout.write(f"  {org_id}: status has no bucket; skip")
                continue

            if server.bucket == bucket:
                unchanged += 1
                continue

            old = server.bucket
            self.stdout.write(f"  {org_id}: {old!r} -> {bucket!r}")
            if live:
                server.bucket = bucket
                server.bucket_region = "us-east-1"
                server.save(update_fields=["bucket", "bucket_region", "updated_at"])
                logger.info(
                    "duckgres_server_bucket_backfilled",
                    organization_id=org_id,
                    old_bucket=old,
                    new_bucket=bucket,
                )
            updated += 1

        verb = "updated" if live else "would update"
        self.stdout.write(
            self.style.SUCCESS(f"Done: {verb} {updated}, unchanged {unchanged}, skipped {skipped} of {total}.")
        )
        if not live and updated:
            self.stdout.write("Re-run with --live-run to apply.")
