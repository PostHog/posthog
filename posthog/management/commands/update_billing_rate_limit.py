import pprint

from django.core.management.base import BaseCommand

from posthog.tasks.billing_rate_limit import update_all_org_billing_rate_limiting


class Command(BaseCommand):
    help = "Update billing rate limiting for all organizations"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of storing it")
        parser.add_argument("--print-reports", type=bool, help="Print the reports in full")
        parser.add_argument(
            "--organization-id", type=str, help="Only calculate the rate limit for this organization ID"
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        organization_id = options["organization_id"]

        results = update_all_org_billing_rate_limiting(dry_run, only_organization_id=organization_id)

        if options["print_reports"]:
            print("")  # noqa T201
            pprint.pprint(results)  # noqa T203
            print("")  # noqa T201

        if dry_run:
            print("Dry run so not stored.")  # noqa T201
        else:
            print(f"{len(results['events'])} orgs rate limited for events")  # noqa T201
            print(f"{len(results['recordings'])} orgs rate limited for recordings")  # noqa T201
            print("Done!")  # noqa T201
