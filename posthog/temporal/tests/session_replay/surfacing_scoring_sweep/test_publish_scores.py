"""Tests for the Kafka writeback path in `score_chunk_activity`.

`_publish_scores` produces JSONEachRow messages onto
`KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS` — the same topic ingestion uses. The
existing `session_replay_events_mv` merges the partial row into the real session
row via `max(surfacing_score)` on the AggregatingMergeTree side. We
verify three pieces of the contract:

1. Payload shape matches what `kafka_session_replay_events` + the MV expect:
   every column the Kafka table has, with identity values for non-score fields
   so the partial row never corrupts the real session's aggregates.
2. `distinct_id` is carried through faithfully — it's the sharding key on
   `writable_session_replay_events`, so a wrong value would route the partial
   row to a different shard than the real session rows.
3. Per-row produce + final flush — the activity must not return until every
   message has been ack'd by the broker, otherwise the workflow happily reports
   `scored=N` while messages are still buffered in librdkafka.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from unittest import mock

import numpy as np
import pandas as pd

from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import _publish_scores
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import KAFKA_PRODUCE_FLUSH_TIMEOUT_S

ACTIVITIES_MODULE = "posthog.temporal.session_replay.surfacing_scoring_sweep.activities"


def _producer_mock(get_producer_mock: mock.MagicMock) -> mock.MagicMock:
    producer = get_producer_mock.return_value
    producer.flush.return_value = 0
    return producer


@pytest.fixture
def id_frame() -> pd.DataFrame:
    """A minimal frame with the four ID columns `_publish_scores` reads from."""
    return pd.DataFrame(
        {
            "team_id": [1, 2, 42],
            "session_id": [
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a1",
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2",
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a3",
            ],
            "distinct_id": ["user-a", "user-b", "user-c"],
            "min_first_timestamp": pd.to_datetime(
                [
                    "2026-05-07 10:00:00+00:00",
                    "2026-05-07 10:01:00+00:00",
                    "2026-05-07 10:02:00+00:00",
                ]
            ),
        }
    )


class TestPublishScores:
    def test_no_rows_skips_producer_entirely(self) -> None:
        empty = pd.DataFrame({"team_id": [], "session_id": [], "distinct_id": [], "min_first_timestamp": []})
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            published = _publish_scores(empty, np.empty(0, dtype=np.float32))
            assert published == 0
            # Empty frame → no producer resolution. Avoids creating the
            # singleton in unit tests that don't exercise the topic.
            get_producer_mock.assert_not_called()

    def test_publishes_one_message_per_row_and_flushes_once(self, id_frame: pd.DataFrame) -> None:
        scores = np.array([0.1, 0.5, 0.9], dtype=np.float32)
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            producer = _producer_mock(get_producer_mock)
            published = _publish_scores(id_frame, scores)

            assert published == 3
            assert producer.produce.call_count == 3

            # Topic fixed across all rows; routes to KafkaClusterProfile.REPLAY.
            for call in producer.produce.call_args_list:
                assert call.kwargs["topic"] == KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS

            # One get_producer() lookup for the loop, none for flush (we reuse
            # the same singleton). flush is called once after the loop.
            get_producer_mock.assert_called_once_with(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS)
            producer.flush.assert_called_once_with(timeout=KAFKA_PRODUCE_FLUSH_TIMEOUT_S)

    def test_payload_carries_score_and_distinct_id(self, id_frame: pd.DataFrame) -> None:
        """The score and distinct_id are the only two non-identity fields in the payload."""
        scores = np.array([0.1, 0.5, 0.9], dtype=np.float32)
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            _producer_mock(get_producer_mock)
            _publish_scores(id_frame, scores)

            payloads = [call.kwargs["data"] for call in get_producer_mock.return_value.produce.call_args_list]
            assert [p["session_id"] for p in payloads] == [
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a1",
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2",
                "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a3",
            ]
            assert [p["team_id"] for p in payloads] == [1, 2, 42]
            assert [p["distinct_id"] for p in payloads] == ["user-a", "user-b", "user-c"]
            assert [p["surfacing_score"] for p in payloads] == [
                pytest.approx(0.1, rel=1e-5),
                pytest.approx(0.5, rel=1e-5),
                pytest.approx(0.9, rel=1e-5),
            ]

    def test_identity_values_preserve_aggregates(self, id_frame: pd.DataFrame) -> None:
        """Every non-score column uses identity values so the partial row
        cannot corrupt the real session's aggregates on the MV side.

        See `_build_partial_row` for the per-column rationale — this test pins
        the contract so a future "let's just send last_timestamp=now()"
        change blows up loudly.
        """
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            _producer_mock(get_producer_mock)
            _publish_scores(id_frame, np.array([0.42, 0.42, 0.42], dtype=np.float32))

            for call in get_producer_mock.return_value.produce.call_args_list:
                payload = call.kwargs["data"]
                # Null arrays / strings → MV's groupArray/argMin drops them.
                assert payload["block_url"] is None
                assert payload["first_url"] is None
                assert payload["snapshot_source"] is None
                assert payload["snapshot_library"] is None
                assert payload["retention_period_days"] is None
                assert payload["urls"] == []
                assert payload["ai_tags_fixed"] == []
                assert payload["ai_tags_freeform"] == []
                # sum() identity = 0.
                assert payload["click_count"] == 0
                assert payload["keypress_count"] == 0
                assert payload["mouse_activity_count"] == 0
                assert payload["active_milliseconds"] == 0
                assert payload["console_log_count"] == 0
                assert payload["console_warn_count"] == 0
                assert payload["console_error_count"] == 0
                assert payload["size"] == 0
                assert payload["event_count"] == 0
                assert payload["message_count"] == 0
                # max(UInt8) identity = 0.
                assert payload["is_deleted"] == 0
                assert payload["ai_highlighted"] == 0

    def test_timestamps_use_session_start_plus_one_microsecond(self) -> None:
        """The partial row's first/last_timestamp = min_first_timestamp + 1µs.

        That guarantees min(first_timestamp) and argMin(first_url, first_timestamp)
        on the MV side keep the real session's earliest row over our partial row.
        """
        session_start = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "team_id": [7],
                "session_id": ["sess-1"],
                "distinct_id": ["user-z"],
                "min_first_timestamp": pd.to_datetime([session_start]),
            }
        )
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            _producer_mock(get_producer_mock)
            _publish_scores(df, np.array([0.42], dtype=np.float32))

            (call,) = get_producer_mock.return_value.produce.call_args_list
            payload = call.kwargs["data"]
            assert payload["first_timestamp"] == "2026-05-07 10:00:00.000001"
            assert payload["last_timestamp"] == "2026-05-07 10:00:00.000001"

    def test_flush_timeout_raises_for_activity_retry(self, id_frame: pd.DataFrame) -> None:
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            producer = get_producer_mock.return_value
            producer.flush.return_value = 2
            with pytest.raises(RuntimeError, match="not delivered"):
                _publish_scores(id_frame, np.array([0.1, 0.5, 0.9], dtype=np.float32))

    def test_score_dtype_is_python_float(self, id_frame: pd.DataFrame) -> None:
        # confluent-kafka-python's JSON serializer can't handle numpy scalars —
        # `float(score)` is the cast that protects us. Pin the behavior so a
        # future "optimization" doesn't pass np.float32 straight through.
        scores = np.array([0.1, 0.5, 0.9], dtype=np.float32)
        with mock.patch(f"{ACTIVITIES_MODULE}.get_producer") as get_producer_mock:
            _producer_mock(get_producer_mock)
            _publish_scores(id_frame, scores)
            for call in get_producer_mock.return_value.produce.call_args_list:
                score = call.kwargs["data"]["surfacing_score"]
                assert type(score) is float
