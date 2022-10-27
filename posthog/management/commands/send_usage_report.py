import pprint

from django.core.management.base import BaseCommand

from posthog.tasks.usage_report import send_all_org_usage_reports
from posthog.utils import wait_for_parallel_celery_group


class Command(BaseCommand):
    help = "Send the usage report for a given day"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--print-reports", type=bool, help="Print the reports in full")
        parser.add_argument("--date", type=str, help="The date to be ran in format YYYY-MM-DD")
        # parser.add_argument("--org-id", type=str, help="The organization ID if only one report should be sent")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        date = options["date"]

        results = send_all_org_usage_reports(dry_run, date)

        if dry_run:
            if options["print_reports"]:
                print("")  # noqa T201
                pprint.pprint(results)  # noqa T203
                print("")  # noqa T201

            print(f"{len(results)} Reports sent!")  # noqa T201
            print("Dry run so not sent.")  # noqa T201
        else:
            print("Done!")  # noqa T201
