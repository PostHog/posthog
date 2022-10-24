import pprint

import dateutil
from django.core.management.base import BaseCommand

from ee.tasks.usage_report import send_all_org_usage_reports


class Command(BaseCommand):
    help = "Send the usage report for a given day"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--date", type=str, help="The date to be ran in format YYYY-MM-DD")
        parser.add_argument("--org-id", type=str, help="The organization ID if only one report should be sent")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        date = options["date"]

        date_parsed = None

        if date:
            date_parsed = dateutil.parser.parse(date)

        reports = send_all_org_usage_reports(dry_run, date_parsed, only_organization_id=options["org_id"])

        if dry_run:
            print("Reports")  # noqa T201
            print("")  # noqa T201
            pprint.pprint(reports)  # noqa T203
            print("")  # noqa T201
            print("Dry run so not sent.")  # noqa T201
        else:
            print("Done!")  # noqa T201
