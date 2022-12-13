import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Migrate cloud billing v1 orgs to v2"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--events_price_map", type=str, help="Map of old to new price IDs")
        parser.add_argument("--recordings_free_price_id", type=str, help="Price ID for free recordings")
        parser.add_argument("--limit", type=int, help="Limit the number of orgs to process")
        parser.add_argument("--organization-id", type=str, help="Only migrate this organization ID")

    def handle(self, *args, **options):
        try:
            from multi_tenancy.migrate_billing import migrate_billing
        except ImportError:
            print("Couldn't import multi_tenancy.migrate_billing")  # noqa T201
            return

        dry_run = options["dry_run"]
        events_price_map = json.loads(options["events_price_map"])
        recordings_free_price_id = options["recordings_free_price_id"]
        limit = options["limit"]
        organization_id = options["organization_id"]

        migrated_orgs = migrate_billing(
            events_price_map,
            recordings_free_price_id,
            dry_run=dry_run,
            limit=limit,
            only_organization_id=organization_id,
        )

        if dry_run:
            print("Dry run so not migrated.")  # noqa T201
        else:
            print(f"{migrated_orgs} orgs migrated!")  # noqa T201
            print("Done!")  # noqa T201
