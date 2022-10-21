import dataclasses
import json

import dateutil
from django.core.management.base import BaseCommand

from ee.tasks.usage_report import send_all_org_usage_reports


class Command(BaseCommand):
    help = "Send the usage report for a given day"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--date", type=bool, help="The date to be ran in format YYYY-MM-DD")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        date = options["date"]

        date_parsed = None

        if date:
            date_parsed = dateutil.parser.parse(date)

        reports = send_all_org_usage_reports(dry_run, date_parsed)

        print([dataclasses.asdict(x) for x in reports])

        json_reports = json.dumps([dataclasses.asdict(x) for x in reports])

        if dry_run:
            print("Reports:")
            print(json_reports)
        else:
            print("Done!")
