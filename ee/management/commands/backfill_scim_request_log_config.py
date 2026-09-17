"""Attribute pre-existing SCIM request logs to the IdP config that now owns the SCIM endpoint.

Usage:
    python manage.py backfill_scim_request_log_config --dry-run
    python manage.py backfill_scim_request_log_config
    python manage.py backfill_scim_request_log_config --organization-id <uuid> --sleep 0.1

SCIM authenticates against an `IdentityProviderConfig`, so requests are logged against it. Rows
logged while SCIM was addressed per domain carry only `organization_domain`, and a config-scoped
query would see a tenant's history start at the deploy. Until this has run, the SCIM log endpoint
matches both keys, so nothing is hidden while the sweep is in progress.

This is a command rather than a migration because the table holds one row per SCIM request and can
be far too large to sweep inside a deploy. Each batch commits on its own, so the sweep can be
stopped and restarted: rows already carrying a config are skipped, and `--start-after` resumes from
the last id a previous run reported.
"""

import time
from argparse import ArgumentParser
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery

import structlog

from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig

from ee.models.scim_request_log import SCIMRequestLog

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1000
PROGRESS_EVERY_BATCHES = 20


class Command(BaseCommand):
    help = "Backfill SCIMRequestLog.identity_provider_config from each row's organization domain."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows updated per transaction (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.0,
            help="Seconds to pause between batches, to keep replicas and IO headroom comfortable.",
        )
        parser.add_argument(
            "--organization-id",
            type=str,
            help="Only sweep logs belonging to this organization, for a staged rollout.",
        )
        parser.add_argument(
            "--start-after",
            type=str,
            help="Resume after this log id, as reported by a previous run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be filled, without writing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        sleep_seconds: float = options["sleep"]
        organization_id: str | None = options.get("organization_id")
        dry_run: bool = options["dry_run"]
        last_id: UUID | None = UUID(options["start_after"]) if options.get("start_after") else None

        pending = SCIMRequestLog.objects.filter(
            identity_provider_config__isnull=True,
            organization_domain__linked_identity_provider_configs__isnull=False,
        )
        if organization_id:
            pending = pending.filter(organization_domain__organization_id=organization_id)

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: {pending.count()} row(s) would be filled"))
            self._report_unattributable(organization_id)
            return

        config_of_domain = Subquery(
            LinkedIdentityProviderConfig.objects.filter(
                organization_domain_id=OuterRef("organization_domain_id")
            ).values("identity_provider_config_id")[:1]
        )

        started_at = time.monotonic()
        updated = 0
        batches = 0

        while True:
            # Walking the primary key keeps the scan forward-only, so the cost doesn't grow with the
            # rows already swept, and a row the update can't fill (its domain lost the config link
            # mid-sweep) can't be picked up again into an endless loop.
            batch_query = pending.order_by("id")
            if last_id is not None:
                batch_query = batch_query.filter(id__gt=last_id)

            batch = list(batch_query.values_list("id", flat=True)[:batch_size])
            if not batch:
                break

            last_id = batch[-1]
            updated += SCIMRequestLog.objects.filter(id__in=batch).update(identity_provider_config=config_of_domain)
            batches += 1

            if batches % PROGRESS_EVERY_BATCHES == 0:
                self.stdout.write(f"{updated} row(s) filled · resume after {last_id}")

            if sleep_seconds:
                time.sleep(sleep_seconds)

        duration = time.monotonic() - started_at
        logger.info("scim_request_log_config_backfilled", rows=updated, duration_seconds=round(duration, 2))
        self.stdout.write(self.style.SUCCESS(f"Filled {updated} row(s) in {duration:.1f}s"))
        self._report_unattributable(organization_id)

    def _report_unattributable(self, organization_id: str | None) -> None:
        # A domain unlinked from its config leaves logs with nothing to attribute them to. They stay
        # reachable through the domain, which is why the SCIM log endpoint still matches both keys.
        orphaned = SCIMRequestLog.objects.filter(
            identity_provider_config__isnull=True,
            organization_domain__linked_identity_provider_configs__isnull=True,
        )
        if organization_id:
            orphaned = orphaned.filter(organization_domain__organization_id=organization_id)

        count = orphaned.count()
        if count:
            self.stdout.write(
                self.style.WARNING(f"{count} row(s) left on their domain key: that domain has no linked IdP config")
            )
