import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client.execute import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.models import ErrorTrackingIssueFingerprintV2
from posthog.models.error_tracking import override_error_tracking_issue_fingerprint

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Simulate a merge for issues that don't have "

    def add_arguments(self, parser):
        parser.add_argument(
            "--fingerprint-start-date",
            required=True,
            type=str,
            help="Minimum timestamp used to look up for fingerprints",
        )
        parser.add_argument(
            "--exception-start-date",
            required=True,
            type=str,
            help="Minimum timestamp used to look up for events (first_seen field)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the command in dry run mode",
        )

    def handle(self, *args, **options):
        fingerprint_start_date = options["fingerprint_start_date"]
        exception_start_date = options["exception_start_date"]
        dry_run = options["dry_run"]

        if dry_run:
            logger.info("dry run mode enabled. No changes will be made")

        query = """
        SELECT
            fo.fingerprint, fo.team_id, fo.max_version, min_timestamp
        FROM
            (
            SELECT
                fingerprint,
                team_id,
                max(version) as max_version
            FROM
                error_tracking_issue_fingerprint_overrides fo
            WHERE
                fo._timestamp > %(fingerprint_start_date)s
            GROUP BY 1, 2
            ) fo
        INNER JOIN
            (SELECT mat_$exception_fingerprint as fingerprint, team_id, min(e.timestamp) as min_timestamp
            FROM events as e
            WHERE e.event = '$exception'
            AND e.timestamp > %(exception_start_date)s
            GROUP BY 1, 2) e
        ON e.fingerprint = fo.fingerprint AND e.team_id = fo.team_id
        """
        logger.info("executing clickhouse query")
        fingerprints = sync_execute(
            query,
            {"exception_start_date": exception_start_date, "fingerprint_start_date": fingerprint_start_date},
        )
        fingerprint_rows = [
            {"fingerprint": row[0], "team_id": row[1], "version": row[2], "timestamp": row[3]} for row in fingerprints
        ]
        logger.info(f"clickhouse query executed. {len(fingerprint_rows)} fingerprints found")
        found_issues_count = 0
        not_found_fingerprints = []

        for fingerprint in fingerprint_rows:
            logger.info("getting postgres fingerprint")
            postgres_fingerprint: ErrorTrackingIssueFingerprintV2 | None = (
                ErrorTrackingIssueFingerprintV2.objects.filter(
                    fingerprint=fingerprint["fingerprint"], team_id=fingerprint["team_id"]
                ).first()
            )
            if postgres_fingerprint is not None:
                logger.info("fingerprint found")
                max_version = max(fingerprint["version"], postgres_fingerprint.version)
                new_version = max_version + 1
                override = {
                    "team_id": fingerprint["team_id"],
                    "issue_id": postgres_fingerprint.issue.id,
                    "fingerprint": postgres_fingerprint.fingerprint,
                    "version": new_version,
                }
                if dry_run is False:
                    postgres_fingerprint.first_seen = fingerprint["timestamp"]
                    postgres_fingerprint.version = new_version
                    logger.info("overriding postgres fingerprint ", override)
                    postgres_fingerprint.save()
                    logger.info("sending fingerprint override to clickhouse ", override)
                    override_error_tracking_issue_fingerprint(**override)
                found_issues_count += 1
            else:
                logger.info("fingerprint not found")
                not_found_fingerprints.append(fingerprint["fingerprint"])

        logger.info(f"fingerprint overriden {found_issues_count}")
        logger.info(f"fingerprints not found {not_found_fingerprints}")
        KafkaProducer().flush(5 * 60)
