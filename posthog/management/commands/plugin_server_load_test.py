import dataclasses
import datetime as dt
import logging
import secrets
import sys
import time
from itertools import chain

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition

from posthog.api.capture import capture_internal
from posthog.demo.products.hedgebox import HedgeboxMatrix
from posthog.models import Team
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION

logging.getLogger("kafka").setLevel(logging.WARNING)  # Hide kafka-python's logspam

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = """
        Uses the HedgeboxMatrix to generate a realistic dataset and sends it to
        Kafka for ingestion by the plugin server, and waits for offset lag to be
        0. You'll need to run the plugin-server and it's dependencies separately
        from running this script.
    """

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--now",
            type=dt.datetime.fromisoformat,
            help="Simulation 'now' datetime in ISO format (default: now)",
        )
        parser.add_argument(
            "--days-past",
            type=int,
            default=120,
            help="At how many days before 'now' should the simulation start (default: 120)",
        )
        parser.add_argument(
            "--days-future",
            type=int,
            default=30,
            help="At how many days after 'now' should the simulation end (default: 30)",
        )
        parser.add_argument(
            "--n-clusters",
            type=int,
            default=500,
            help="Number of clusters (default: 500)",
        )
        parser.add_argument(
            "--team-id",
            type=str,
            default="1",
            help="The team to which the events should be associated.",
        )

    def handle(self, *args, **options):
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.UTC)

        admin = KafkaAdminClient(bootstrap_servers=settings.KAFKA_HOSTS)
        consumer = KafkaConsumer(KAFKA_EVENTS_PLUGIN_INGESTION, bootstrap_servers=settings.KAFKA_HOSTS)
        team = Team.objects.filter(id=int(options["team_id"])).first()
        if not team:
            logger.critical("Cannot find team with id: " + options["team_id"])
            exit(1)
        token = team.api_token

        logger.info(
            "creating_data",
            seed=seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
        )
        matrix = HedgeboxMatrix(
            seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
        )
        matrix.simulate()

        # Make sure events are ordered by time to simulate how they would be
        # ingested in real life.
        ordered_events = sorted(
            chain.from_iterable(person.all_events for person in matrix.people),
            key=lambda e: e.timestamp,
        )

        start_time = time.monotonic()
        for event in ordered_events:
            capture_internal(
                event={
                    **dataclasses.asdict(event),
                    "timestamp": event.timestamp.isoformat(),
                    "person_id": str(event.person_id),
                    "person_created_at": event.person_created_at.isoformat(),
                },
                distinct_id=event.distinct_id,
                ip="",
                site_url="",
                token=token,
                now=event.timestamp,
                sent_at=event.timestamp,
            )

        while True:
            offsets = admin.list_consumer_group_offsets(group_id="clickhouse-ingestion")
            end_offsets = consumer.end_offsets([TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION, partition=0)])
            if end_offsets is None:
                logger.error(
                    "no_end_offsets",
                    topic=KAFKA_EVENTS_PLUGIN_INGESTION,
                    partition=0,
                )
                sys.exit(1)

            end_offset = end_offsets[TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION, partition=0)]
            offset = offsets[TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION, partition=0)].offset
            logger.info("offset_lag", offset=offset, end_offset=end_offset)
            if end_offset == offset:
                break
            time.sleep(1)

        logger.info("load_test_completed", time_taken=time.monotonic() - start_time)
