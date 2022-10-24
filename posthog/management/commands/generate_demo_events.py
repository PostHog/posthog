import dataclasses
import datetime as dt
import logging
import secrets
import time
from itertools import chain

import structlog
from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition

from posthog.api.capture import capture_internal
from posthog.demo.products.hedgebox import HedgeboxMatrix
from posthog.settings import KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC

logging.getLogger("kafka").setLevel(logging.WARNING)  # Hide kafka-python's logspam

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Generate events using a method that should generate roughly realistic data."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--now", type=dt.datetime.fromisoformat, help="Simulation 'now' datetime in ISO format (default: now)"
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
        parser.add_argument("--n-clusters", type=int, default=500, help="Number of clusters (default: 500)")
        parser.add_argument(
            "--team-id", type=str, default="1", help="The team to which the events should be associated."
        )

    def handle(self, *args, **options):
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.timezone.utc)
        logger.info("Instantiating the Matrix...")
        matrix = HedgeboxMatrix(
            seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
        )
        logger.info("Running simulation...")
        matrix.simulate()
        ordered_events = sorted(
            chain.from_iterable(person.all_events for person in matrix.people), key=lambda e: e.timestamp
        )

        admin = KafkaAdminClient(bootstrap_servers="localhost:9092")
        consumer = KafkaConsumer(KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, bootstrap_servers="localhost:9092")

        start_time = time.monotonic()
        for event in ordered_events:
            capture_internal(
                event={
                    **dataclasses.asdict(event),
                    "timestamp": event.timestamp.isoformat(),
                },
                distinct_id=event.distinct_id,
                ip="",
                site_url="",
                team_id=options["team_id"],
                now=event.timestamp,
                sent_at=event.timestamp,
            )

        while True:
            offsets = admin.list_consumer_group_offsets(group_id="clickhouse-ingestion")
            end_offsets = consumer.end_offsets([TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, partition=0)])
            endOffset = end_offsets[TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, partition=0)]
            offset = offsets[TopicPartition(topic=KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, partition=0)].offset
            logger.info(f"Offset: {offset} / {endOffset}")
            if endOffset == offset:
                break
            time.sleep(1)

        logger.info(f"Time taken: {time.monotonic() - start_time}")
