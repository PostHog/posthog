import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client.execute import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS

from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Backfill embedding requests for error tracking issue fingerprints"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            required=True,
            type=str,
            help="Minimum timestamp used to look up for fingerprints",
        )
        parser.add_argument(
            "--end-date",
            required=True,
            type=str,
            help="Maximum timestamp used to look up for fingerprints",
        )
        parser.add_argument(
            "--team-id",
            required=True,
            type=int,
            help="Team ID to filter by",
        )

    def handle(self, *args, **options):
        fingerprint_start_date = options["start_date"]
        fingerprint_end_date = options["end_date"]
        team_id = options["team_id"]

        # Fetch the fingerprints
        fingerprints = (
            ErrorTrackingIssueFingerprintV2.objects.filter(
                team_id=team_id,
                created_at__gte=fingerprint_start_date,
                created_at__lte=fingerprint_end_date,
            )
            .order_by("created_at")
            .iterator()
        )

        # Iterate through the fingerprints in batches of 100 at a time
        batch: list[ErrorTrackingIssueFingerprintV2] = []
        for fingerprint in fingerprints:
            batch.append(fingerprint)
            if len(batch) == 100:
                events = create_embedding_events(batch)
                for event in events:
                    KafkaProducer().produce(KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS, event)
                logger.info(f"Processed {len(batch)} fingerprints, last created_at: {batch[-1].created_at}")
                batch.clear()

        if len(batch) > 0:
            events = create_embedding_events(batch)
            for event in events:
                KafkaProducer().produce(KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS, event)
            logger.info(f"Processed {len(batch)} fingerprints, last created_at: {batch[-1].created_at}")
            batch.clear()

        KafkaProducer().flush(5 * 60)


def create_embedding_events(batch: list[ErrorTrackingIssueFingerprintV2]):
    logger.info(f"Creating embedding events for {len(batch)} fingerprints")
    # Go to clickhouse to fetch an event for each fingerprint
    event_query = """
        SELECT properties FROM events
        WHERE event = '$exception'
        AND team_id = %(team_id)s
        AND timestamp BETWEEN %(start)s AND %(end)s
        AND mat_$exception_fingerprint = %(fingerprint)s
        ORDER BY timestamp ASC
        LIMIT 1
    """
    new_fingerprint_events = []
    for fingerprint in batch:
        # Technically first_seen is nullable
        start_time = fingerprint.first_seen if fingerprint.first_seen else fingerprint.created_at
        properties = sync_execute(
            event_query,
            {
                "team_id": fingerprint.team_id,
                "start": start_time,
                "end": start_time + timedelta(hours=1),
                "fingerprint": fingerprint.fingerprint,
            },
        )
        if not properties:
            logger.warning(f"No event found for fingerprint {fingerprint.fingerprint}")
            continue

        properties = json.loads(properties[0][0])
        event = create_new_fingerprint_event(fingerprint, properties)
        if event:
            event["models"] = ["text-embedding-3-large"]
            new_fingerprint_events.append(event)

    logger.info(f"Created embedding events for {len(new_fingerprint_events)} fingerprints")
    return new_fingerprint_events


def create_new_fingerprint_event(fingerprint: ErrorTrackingIssueFingerprintV2, properties):
    exception_list = []
    for exception in properties["$exception_list"]:
        data = {
            "exception_type": exception["type"],
            "exception_value": exception["value"],
        }
        if exception["stacktrace"] and exception["stacktrace"]["frames"]:
            data["frames"] = exception["stacktrace"]["frames"]
        exception_list.append(data)
    event = {
        "team_id": int(fingerprint.team_id),
        "fingerprint": str(fingerprint.fingerprint),
        "exception_list": exception_list,
    }
    return event
