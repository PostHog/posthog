from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from posthog.kafka_client.dlq_replay import drain_dlq


class Command(BaseCommand):
    help = "Replay a Kafka DLQ topic back into its target topic using a consumer group."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--source-topic", required=True, help="DLQ topic to read from")
        parser.add_argument("--target-topic", required=True, help="Topic to replay messages to")
        parser.add_argument(
            "--group-id",
            default="dlq-replay-ingestion-traces",
            help="Consumer group id; reuse the same id to resume an interrupted run",
        )
        parser.add_argument("--max-replays", type=int, default=2, help="Skip a message replayed this many times")
        parser.add_argument("--batch-size", type=int, default=500, help="Messages to consume per poll")
        parser.add_argument("--idle-polls", type=int, default=2, help="Stop after this many consecutive empty polls")
        parser.add_argument("--poll-timeout-seconds", type=float, default=5.0, help="Seconds to wait per poll")
        parser.add_argument("--bootstrap-servers", default=None, help="Override brokers instead of topic routing")
        parser.add_argument("--security-protocol", default=None, help="Override the security protocol")
        parser.add_argument("--dry-run", action="store_true", help="Count without producing or committing")

    def handle(self, *args: Any, **options: Any) -> None:
        result = drain_dlq(
            source_topic=options["source_topic"],
            target_topic=options["target_topic"],
            group_id=options["group_id"],
            max_replays=options["max_replays"],
            batch_size=options["batch_size"],
            idle_polls=options["idle_polls"],
            poll_timeout_seconds=options["poll_timeout_seconds"],
            dry_run=options["dry_run"],
            bootstrap_servers=options["bootstrap_servers"],
            security_protocol=options["security_protocol"],
            log=lambda message: self.stdout.write(message),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Replayed {result['replayed']}, exhausted {result['exhausted']}, errors {result['errors']}"
            )
        )
