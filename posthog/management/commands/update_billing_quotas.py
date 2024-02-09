import pprint

from django.core.management.base import BaseCommand

from ee.billing.quota_limiting import update_all_org_billing_quotas


class Command(BaseCommand):
    help = "Update billing rate limiting for all organizations"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of storing it")
        parser.add_argument("--print-reports", type=bool, help="Print the reports in full")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas(dry_run)

        if options["print_reports"]:
            print("Quota Limited Orgs")  # noqa T201
            pprint.pprint(quota_limited_orgs)  # noqa T203
            print("Quota Limiting Suspended Orgs")  # noqa T201
            pprint.pprint(data_retained_orgs)  # noqa T203

        if dry_run:
            print("Dry run so not stored.")  # noqa T201
        else:
            print(f"{len(quota_limited_orgs['events'])} orgs rate limited for events")  # noqa T201
            print(f"{len(data_retained_orgs['events'])} orgs quota limiting suspended for events")  # noqa T201
            print(f"{len(quota_limited_orgs['recordings'])} orgs rate limited for recordings")  # noqa T201
            print(f"{len(data_retained_orgs['recordings'])} orgs quota limiting suspended for recordings")  # noqa T201
            print("Done!")  # noqa T201
