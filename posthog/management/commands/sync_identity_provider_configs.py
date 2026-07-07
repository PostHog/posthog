from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.models.identity_provider_config import sync_identity_provider_config_from_domain
from posthog.models.organization_domain import OrganizationDomain

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "One-time backfill of IdentityProviderConfig rows from OrganizationDomain's legacy "
        "SAML/SCIM/XAA columns (no longer written to by the app). Creates a config for every "
        "domain with IdP settings and links it; re-running updates any drifted configs. Idempotent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--organization-id",
            type=str,
            default=None,
            help="Only sync domains belonging to this organization ID.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        organization_id: str | None = options["organization_id"]

        queryset = OrganizationDomain.objects.select_related("identity_provider_config").order_by(
            "organization_id", "domain"
        )
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)

        counts: Counter[str] = Counter()
        for domain in queryset.iterator(chunk_size=500):
            action = sync_identity_provider_config_from_domain(domain, dry_run=dry_run)
            counts[action] += 1
            if action in ("created", "updated"):
                self.stdout.write(
                    f"{'[DRY RUN] would have ' if dry_run else ''}{action}: domain={domain.domain} "
                    f"organization={domain.organization_id} config={domain.identity_provider_config_id or '<new>'}"
                )

        total = sum(counts.values())
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Processed {total} domain(s): "
                f"{counts['created']} created, {counts['updated']} updated, "
                f"{counts['unchanged']} unchanged, {counts['skipped']} skipped (no IdP settings)"
            )
        )
