from collections import defaultdict
from uuid import UUID

from django.core.management.base import BaseCommand

from posthog.models import Organization
from posthog.models.identity_provider_config import IdentityProviderConfig


class Command(BaseCommand):
    help = (
        "Backfill Organization.is_saml_enabled/is_scim_enabled/is_id_jag_enabled from the "
        "organization's IdentityProviderConfig rows: each flag is set if at least one linked "
        "config is complete enough for that feature (scim_enabled=True for SCIM; has_saml/"
        "has_id_jag for SAML/ID-JAG)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of organizations to process per batch (default: 1000)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # OR each organization's flags across all of its configs.
        org_flags: dict[UUID, dict[str, bool]] = defaultdict(lambda: {"saml": False, "scim": False, "id_jag": False})

        configs = IdentityProviderConfig.objects.only(
            "organization", "saml_entity_id", "saml_acs_url", "saml_x509_cert", "scim_enabled", "id_jag_issuer_url"
        )
        for config in configs.iterator(chunk_size=batch_size):
            flags = org_flags[config.organization_id]
            flags["saml"] = flags["saml"] or config.has_saml
            flags["scim"] = flags["scim"] or config.scim_enabled
            flags["id_jag"] = flags["id_jag"] or config.has_id_jag

        org_ids_with_configs = list(org_flags.keys())
        total = len(org_ids_with_configs)
        self.stdout.write(f"Found {total} organizations with at least one identity provider config")

        if total == 0:
            self.stdout.write("Nothing to backfill.")
            return

        queryset = Organization.objects.filter(id__in=org_ids_with_configs).only(
            "id", "is_saml_enabled", "is_scim_enabled", "is_id_jag_enabled"
        )

        processed = 0
        updated = 0
        pending_updates: list[Organization] = []

        for org in queryset.iterator(chunk_size=batch_size):
            processed += 1
            flags = org_flags[org.id]

            new_saml_enabled = flags["saml"]
            new_scim_enabled = flags["scim"]
            new_id_jag_enabled = flags["id_jag"]

            if (
                new_saml_enabled == org.is_saml_enabled
                and new_scim_enabled == org.is_scim_enabled
                and new_id_jag_enabled == org.is_id_jag_enabled
            ):
                continue

            org.is_saml_enabled = new_saml_enabled
            org.is_scim_enabled = new_scim_enabled
            org.is_id_jag_enabled = new_id_jag_enabled
            pending_updates.append(org)
            updated += 1

            if not dry_run and len(pending_updates) >= batch_size:
                Organization.objects.bulk_update(
                    pending_updates, ["is_saml_enabled", "is_scim_enabled", "is_id_jag_enabled"]
                )
                pending_updates = []

            if processed % batch_size == 0:
                self.stdout.write(f"Progress: {processed}/{total} processed, {updated} flagged for update")

        if not dry_run and pending_updates:
            Organization.objects.bulk_update(
                pending_updates, ["is_saml_enabled", "is_scim_enabled", "is_id_jag_enabled"]
            )

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            f"\n{'Dry run complete' if dry_run else 'Backfill complete'}. {action} {updated} of {total} organizations."
        )
