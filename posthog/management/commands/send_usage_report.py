import pprint

import dateutil
import structlog
from django.core.management.base import BaseCommand

from ee.tasks.usage_report import send_all_org_usage_reports

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Send the usage report for a given day"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--date", type=str, help="The date to be ran in format YYYY-MM-DD")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        date = options["date"]

        date_parsed = None

        if date:
            date_parsed = dateutil.parser.parse(date)

        reports = send_all_org_usage_reports(dry_run, date_parsed)

        if dry_run:
            logger.info("Reports")
            pprint.pprint(reports)
        else:
            logger.info("Done!")
