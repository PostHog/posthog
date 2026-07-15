import logging

from django.core.management.base import BaseCommand

from posthog.models.identity_provider_config import IdentityProviderConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Backfill IdentityProviderConfig.saml_relay_state from the linked OrganizationDomain's id. "
        "Only populates configs linked from exactly one domain; configs linked from zero or "
        "multiple domains are left untouched. Idempotent (skips configs already populated)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        updated = 0
        skipped_no_domain = 0
        skipped_multiple_domains = 0

        queryset = IdentityProviderConfig.objects.filter(saml_relay_state__isnull=True)
        for config in queryset.iterator(chunk_size=1000):
            # `domains` is the reverse of `OrganizationDomain.identity_provider_config`. Only act
            # when the link is unambiguous — skip rather than guess which domain's id to use.
            domain_ids = list(config.domains.values_list("id", flat=True)[:2])
            if not domain_ids:
                skipped_no_domain += 1
                continue
            if len(domain_ids) > 1:
                skipped_multiple_domains += 1
                self.stdout.write(f"  config={config.pk} linked from multiple domains; skipping (not 1:1)")
                continue

            updated += 1
            self.stdout.write(f"  config={config.pk} -> saml_relay_state={domain_ids[0]}")
            if not dry_run:
                config.saml_relay_state = str(domain_ids[0])
                config.save(update_fields=["saml_relay_state"])

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            f"{verb} {updated} config(s). Skipped {skipped_no_domain} with no linked domain and "
            f"{skipped_multiple_domains} linked from multiple domains."
        )
