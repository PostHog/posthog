import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from ee.clickhouse.materialized_columns.analyze import (
    logger,
)


class Command(BaseCommand):
    help = "Restore Django snapshots from S3"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print plan instead of executing it")
        parser.add_argument("--json", help="JSON file to restore from")

    def handle(self, *, dry_run: bool, **options):
        logger.setLevel(logging.INFO)
        if not settings.DEBUG:
            raise RuntimeError("This command is only available in debug mode")
