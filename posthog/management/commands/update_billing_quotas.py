import pprint

from django.core.management.base import BaseCommand

from ee.billing.quota_limiting import update_all_orgs_billing_quotas


class Command(BaseCommand):
    help = "Update billing rate limiting for all organizations"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of storing it")
        parser.add_argument("--print-reports", type=bool, help="Print the reports in full")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        quota_limited_orgs, quota_limiting_suspended_orgs = update_all_orgs_billing_quotas(dry_run)

        if options["print_reports"]:
            print("")  # noqa T201
            pprint.pprint(quota_limited_orgs)  # noqa T203
            pprint.pprint(quota_limiting_suspended_orgs)  # noqa T203
            print("")  # noqa T201

        if dry_run:
            print("Dry run so not stored.")  # noqa T201
        else:
            print(f"{len(quota_limited_orgs['events'])} orgs rate limited for events")  # noqa T201
            print(  # noqa T201
                f"{len(quota_limiting_suspended_orgs['events'])} orgs rate limiting suspended for events"  # noqa T201
            )  # noqa T201
            print(f"{len(quota_limited_orgs['recordings'])} orgs rate limited for recordings")  # noqa T201
            print(  # noqa T201
                f"{len(quota_limiting_suspended_orgs['recordings'])} orgs rate limiting suspended for recordings"  # noqa T201
            )  # noqa T201
            print("Done!")  # noqa T201
