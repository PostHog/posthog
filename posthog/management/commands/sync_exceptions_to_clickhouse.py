import logging

import structlog
from django.core.management.base import BaseCommand
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.error_tracking import override_error_tracking_issue_fingerprint

from posthog.models import ErrorTrackingIssueFingerprintV2

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Make sure exceptions in events table have the right associated fingerprint"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since_ts",
            required=True,
            type=str,
            help="Sync exceptions since this timestap",
        )

    def handle(self, *args, **options):
        since_ts = options["since_ts"]
        query = """
        SELECT
            issue_id,
            team_id,
            version,
            fingerprint,
            _timestamp,
        FROM error_tracking_issue_fingerprint_overrides
        WHERE _timestamp > %(since_ts)s
        """
        exceptions = sync_execute(
            query,
            {
                "since_ts": since_ts,
            },
        )
        exception_rows = [
            {"issue_id": row[0], "team_id": row[1], "version": row[2], "fingerprint": row[3], "timestamp": row[4]}
            for row in exceptions
        ]

        for exception in exception_rows:
            postgres_exception: ErrorTrackingIssueFingerprintV2 = ErrorTrackingIssueFingerprintV2.objects.filter(
                fingerprint=exception["fingerprint"]
            ).get()
            if postgres_exception is not None:
                ## Send event to clickhouse with issue id and incremented version to simulate an issue merge
                override = {
                    "team_id": exception["team_id"],
                    "issue_id": postgres_exception.issue.id,
                    "fingerprint": postgres_exception.fingerprint,
                    "version": exception["version"] + 1,
                }
                logger.info("sending fingerprint override ", override)
                override_error_tracking_issue_fingerprint(**override)
