import json

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.customer_analytics.backend.logic.person_property_update_consumer import (
    DLQ,
    RETRY,
    SENT,
    InvalidPersonPropertyMessage,
    PersonPropertyUpdateConsumer,
    TokenBucket,
    build_capture_kwargs,
)


class TestTokenBucket:
    def test_blocks_until_a_token_is_available_then_proceeds(self):
        # A fake clock that doesn't advance on its own; sleep advances it. At 10/sec one token
        # takes 0.1s, so the first acquire on an empty bucket sleeps ~0.1s once.
        clock = {"t": 0.0}
        sleeps: list[float] = []

        def now():
            return clock["t"]

        def sleep(seconds):
            sleeps.append(seconds)
            clock["t"] += seconds

        bucket = TokenBucket(lambda: 10.0, now=now, sleep=sleep)
        bucket.acquire()

        assert sleeps  # it had to wait
        assert abs(sum(sleeps) - 0.1) < 1e-6

    def test_accumulated_tokens_allow_a_burst_without_sleeping(self):
        clock = {"t": 0.0}

        def now():
            return clock["t"]

        def sleep(seconds):
            clock["t"] += seconds

        bucket = TokenBucket(lambda: 100.0, now=now, sleep=sleep)
        clock["t"] = 1.0  # 1s elapsed -> ~100 tokens accrued (capped at rate)
        for _ in range(50):
            bucket.acquire()  # should not need to sleep
        assert clock["t"] == 1.0


class TestBuildCaptureKwargs:
    def test_maps_to_set_event_with_person_processing(self):
        kwargs = build_capture_kwargs(
            {"token": "tok", "distinct_id": 42, "properties": {"plan_tier": "pro"}, "event_source": "x"}
        )
        assert kwargs == {
            "token": "tok",
            "event_name": "$set",
            "event_source": "x",
            "distinct_id": "42",
            "properties": {"$set": {"plan_tier": "pro"}},
            "process_person_profile": True,
        }

    @parameterized.expand(
        [
            ("missing_token", {"distinct_id": "a", "properties": {"p": 1}}),
            ("missing_distinct_id", {"token": "t", "properties": {"p": 1}}),
            ("empty_properties", {"token": "t", "distinct_id": "a", "properties": {}}),
            ("non_dict_properties", {"token": "t", "distinct_id": "a", "properties": "nope"}),
        ]
    )
    def test_rejects_unusable_messages(self, _name, payload):
        with pytest.raises(InvalidPersonPropertyMessage):
            build_capture_kwargs(payload)


def _capture_result(*, succeeded: bool, dropped: list[str] | None = None) -> MagicMock:
    return MagicMock(succeeded=MagicMock(return_value=succeeded), dropped=dropped or [])


class TestProcessRecord:
    def _consumer(self, capture_fn, dlq=None):
        # No-op token bucket so tests don't sleep.
        bucket = MagicMock()
        return PersonPropertyUpdateConsumer(capture_fn=capture_fn, bucket=bucket, dlq_producer=dlq or MagicMock())

    def test_successful_send_commits(self):
        capture = MagicMock(return_value=_capture_result(succeeded=True))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == SENT
        assert capture.call_args.kwargs["event_name"] == "$set"
        assert capture.call_args.kwargs["process_person_profile"] is True

    def test_transient_capture_failure_is_left_for_retry(self):
        # Not succeeded and nothing dropped -> transient (exhausted retries / unaccounted): redeliver.
        capture = MagicMock(return_value=_capture_result(succeeded=False))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    def test_capture_exception_is_left_for_retry(self):
        capture = MagicMock(side_effect=RuntimeError("capture down"))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    def test_terminal_drop_goes_to_dlq_not_retry(self):
        # A dropped event is a permanent rejection (bad token, validation): DLQ it so it can't be
        # redelivered forever and wedge the partition.
        capture = MagicMock(return_value=_capture_result(succeeded=False, dropped=["uid"]))
        dlq = MagicMock()
        c = self._consumer(capture, dlq=dlq)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == DLQ
        dlq.produce.assert_called_once()

    @parameterized.expand(
        [
            ("invalid_json", b"not json"),
            ("non_object_array", b"[]"),
            ("non_object_string", b'"foo"'),
            ("non_object_null", b"null"),
            ("poison_shape", json.dumps({"distinct_id": "a", "properties": {"p": 1}}).encode()),
        ]
    )
    def test_poison_messages_go_to_dlq(self, _name, value):
        capture = MagicMock()
        dlq = MagicMock()
        c = PersonPropertyUpdateConsumer(capture_fn=capture, bucket=MagicMock(), dlq_producer=dlq)

        assert c.process_record(value) == DLQ
        dlq.produce.assert_called_once()
        capture.assert_not_called()

    def test_failed_dlq_delivery_is_retried_not_dropped(self):
        # If the DLQ write itself fails to deliver, we must not commit the source offset: return
        # RETRY so the poison message is redelivered instead of vanishing from both topics.
        capture = MagicMock()
        dlq = MagicMock()
        dlq.produce.return_value.get.side_effect = RuntimeError("delivery failed")
        c = PersonPropertyUpdateConsumer(capture_fn=capture, bucket=MagicMock(), dlq_producer=dlq)

        assert c.process_record(b"not json") == RETRY

    def test_dlq_producer_is_resolved_once_and_reused(self):
        # A poison-heavy partition must not resolve a new producer per message; the routed singleton
        # is fetched lazily on first use and cached.
        with patch(
            "products.customer_analytics.backend.logic.person_property_update_consumer.get_producer"
        ) as get_producer:
            c = PersonPropertyUpdateConsumer(capture_fn=MagicMock(), bucket=MagicMock())
            c.process_record(b"not json")
            c.process_record(b"still not json")

        get_producer.assert_called_once()
        assert get_producer.return_value.produce.call_count == 2
