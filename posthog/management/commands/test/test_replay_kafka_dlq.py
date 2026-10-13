from unittest import TestCase

from parameterized import parameterized

from posthog.kafka_client.dlq_replay import DLQ_REPLAY_PIPELINES
from posthog.kafka_client.topics import (
    KAFKA_LOGS_INGESTION,
    KAFKA_LOGS_INGESTION_DLQ,
    KAFKA_TRACES_INGESTION,
    KAFKA_TRACES_INGESTION_DLQ,
)
from posthog.management.commands.replay_kafka_dlq import resolve_pipeline


class ResolvePipelineTest(TestCase):
    @parameterized.expand(
        [
            (
                "traces_preset",
                {"pipeline": "traces"},
                (KAFKA_TRACES_INGESTION_DLQ, KAFKA_TRACES_INGESTION, "dlq-replay-ingestion-traces"),
            ),
            (
                "logs_preset",
                {"pipeline": "logs"},
                (KAFKA_LOGS_INGESTION_DLQ, KAFKA_LOGS_INGESTION, "dlq-replay-ingestion-logs"),
            ),
            (
                "explicit_topics_keep_preset_group",
                {"pipeline": "traces", "source_topic": "custom-dlq", "target_topic": "custom"},
                ("custom-dlq", "custom", "dlq-replay-ingestion-traces"),
            ),
            (
                "explicit_group_keeps_preset_topics",
                {"pipeline": "logs", "group_id": "dlq-replay-logs-retry"},
                (KAFKA_LOGS_INGESTION_DLQ, KAFKA_LOGS_INGESTION, "dlq-replay-logs-retry"),
            ),
        ]
    )
    def test_applies_overrides_on_top_of_preset(
        self, _name: str, options: dict[str, str], expected: tuple[str, str, str]
    ) -> None:
        pipeline = resolve_pipeline(**options)

        assert (pipeline.source_topic, pipeline.target_topic, pipeline.group_id) == expected

    def test_every_preset_drains_a_distinct_topic_pair(self) -> None:
        pairs = {(p.source_topic, p.target_topic) for p in DLQ_REPLAY_PIPELINES.values()}
        assert len(pairs) == len(DLQ_REPLAY_PIPELINES)
        assert all(p.source_topic != p.target_topic for p in DLQ_REPLAY_PIPELINES.values())
