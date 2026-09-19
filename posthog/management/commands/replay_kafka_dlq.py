import signal
import dataclasses
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.kafka_client.dlq_replay import DLQ_REPLAY_PIPELINES, DLQReplayPipeline, drain_dlq


def _parse_team_ids(raw: str) -> frozenset[int]:
    return frozenset(int(part) for part in raw.split(",") if part.strip())


def resolve_pipeline(
    pipeline: str,
    source_topic: str | None = None,
    target_topic: str | None = None,
    group_id: str | None = None,
) -> DLQReplayPipeline:
    """Start from the named pipeline and apply any topic or group id given on the command line."""
    overrides = {
        name: value
        for name, value in (
            ("source_topic", source_topic),
            ("target_topic", target_topic),
            ("group_id", group_id),
        )
        if value is not None
    }
    return dataclasses.replace(DLQ_REPLAY_PIPELINES[pipeline], **overrides)


class Command(BaseCommand):
    help = "Replay a Kafka DLQ topic back into its target topic using a consumer group."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--pipeline",
            choices=sorted(DLQ_REPLAY_PIPELINES),
            default="traces",
            help="Ingestion pipeline whose DLQ to drain; sets the topics and group id unless overridden",
        )
        parser.add_argument("--source-topic", default=None, help="DLQ topic to read from")
        parser.add_argument("--target-topic", default=None, help="Topic to replay messages to")
        parser.add_argument(
            "--group-id",
            default=None,
            help="Consumer group id; reuse the same id to resume an interrupted run",
        )
        parser.add_argument("--max-replays", type=int, default=2, help="Skip a message replayed this many times")
        parser.add_argument("--batch-size", type=int, default=500, help="Messages to consume per poll")
        parser.add_argument("--idle-polls", type=int, default=2, help="Stop after this many consecutive empty polls")
        parser.add_argument("--poll-timeout-seconds", type=float, default=5.0, help="Seconds to wait per poll")
        parser.add_argument("--bootstrap-servers", default=None, help="Override brokers instead of topic routing")
        parser.add_argument("--security-protocol", default=None, help="Override the security protocol")
        parser.add_argument(
            "--skip-team-ids",
            type=_parse_team_ids,
            default=frozenset(),
            help="Comma-separated team ids to read past without replaying; they stay on the DLQ",
        )
        parser.add_argument(
            "--max-messages-per-second",
            type=float,
            default=None,
            help="Cap the replay produce rate; unset means no limit",
        )
        parser.add_argument(
            "--max-message-bytes",
            type=int,
            default=None,
            help="Largest record to produce, in bytes; unset uses KAFKA_<PROFILE>_PRODUCER_MAX_REQUEST_SIZE, then 1 MiB",
        )
        parser.add_argument("--dry-run", action="store_true", help="Count without producing or committing")

    def handle(self, *args: Any, **options: Any) -> None:
        stop_requested = {"value": False}

        def request_stop(_signum: int, _frame: Any) -> None:
            stop_requested["value"] = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        pipeline = resolve_pipeline(
            options["pipeline"],
            source_topic=options["source_topic"],
            target_topic=options["target_topic"],
            group_id=options["group_id"],
        )
        self.stdout.write(
            f"Draining {pipeline.source_topic} into {pipeline.target_topic} with group {pipeline.group_id}"
        )
        result = drain_dlq(
            source_topic=pipeline.source_topic,
            target_topic=pipeline.target_topic,
            group_id=pipeline.group_id,
            max_replays=options["max_replays"],
            batch_size=options["batch_size"],
            idle_polls=options["idle_polls"],
            poll_timeout_seconds=options["poll_timeout_seconds"],
            dry_run=options["dry_run"],
            bootstrap_servers=options["bootstrap_servers"],
            security_protocol=options["security_protocol"],
            skip_team_ids=options["skip_team_ids"],
            max_messages_per_second=options["max_messages_per_second"],
            max_message_bytes=options["max_message_bytes"],
            should_stop=lambda: stop_requested["value"],
            log=lambda message: self.stdout.write(message),
        )
        counts = (
            f"Replayed {result['replayed']}, exhausted {result['exhausted']}, "
            f"skipped {result['skipped']}, errors {result['errors']}"
        )
        if result["errors"]:
            raise CommandError(f"{counts}. The DLQ is not drained, so rerun with the same --group-id.")
        self.stdout.write(self.style.SUCCESS(counts))
