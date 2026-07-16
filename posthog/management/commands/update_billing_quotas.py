import pprint

from django.core.management.base import BaseCommand

from ee.billing.quota_limiting import update_all_orgs_billing_quotas


class Command(BaseCommand):
    help = "Update billing rate limiting for all organizations"

    def add_arguments(self, parser):
        # store_true, not type=bool: argparse applies bool() to the raw string, so
        # `--dry-run false` would silently parse as True.
        parser.add_argument("--dry-run", action="store_true", help="Print information instead of storing it")
        parser.add_argument("--print-reports", action="store_true", help="Print the reports in full")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas(dry_run)

        if options["print_reports"]:
            print("")  # noqa T201
            pprint.pprint(quota_limited_orgs)  # noqa T203
            pprint.pprint(quota_limiting_suspended_orgs)  # noqa T203
            print("")  # noqa T201

        if dry_run:
            print("Dry run so not stored.")  # noqa T201

        for resource, limited in quota_limited_orgs.items():
            if limited:
                print(f"{len(limited)} orgs {'would be ' if dry_run else ''}rate limited for {resource}")  # noqa T201
        for resource, suspended in quota_limiting_suspended_orgs.items():
            if suspended:
                print(  # noqa T201
                    f"{len(suspended)} orgs {'would have ' if dry_run else ''}rate limiting suspended for {resource}"
                )

        if not dry_run:
            print("Done!")  # noqa T201
