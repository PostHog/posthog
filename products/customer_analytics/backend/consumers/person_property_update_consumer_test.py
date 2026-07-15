import json

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.customer_analytics.backend.consumers.person_property_update_consumer import (
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


class TestProcessRecord:
    def _consumer(self, capture_fn):
        # No-op token bucket so tests don't sleep.
        bucket = MagicMock()
        return PersonPropertyUpdateConsumer(capture_fn=capture_fn, bucket=bucket, dlq_producer=MagicMock())

    def test_successful_send_commits(self):
        capture = MagicMock(return_value=MagicMock(succeeded=MagicMock(return_value=True)))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == SENT
        assert capture.call_args.kwargs["event_name"] == "$set"
        assert capture.call_args.kwargs["process_person_profile"] is True

    def test_capture_failure_is_left_for_retry(self):
        capture = MagicMock(return_value=MagicMock(succeeded=MagicMock(return_value=False)))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    def test_capture_exception_is_left_for_retry(self):
        capture = MagicMock(side_effect=RuntimeError("capture down"))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    @parameterized.expand(
        [
            ("invalid_json", b"not json"),
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
