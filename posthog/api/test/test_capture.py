import base64
import gzip
import json
import pathlib
import random
import string
import zlib
from collections import Counter
from datetime import datetime, timedelta
from datetime import timezone as tz
from typing import Any, Dict, List, Union, cast
from unittest import mock
from unittest.mock import ANY, MagicMock, call, patch
from urllib.parse import quote
import lzstring
import pytest
import structlog
from django.test.client import Client
from django.utils import timezone
from freezegun import freeze_time
from kafka.errors import KafkaError
from kafka.producer.future import FutureProduceResult, FutureRecordMetadata
from kafka.structs import TopicPartition
from parameterized import parameterized
from prance import ResolvingParser
from rest_framework import status
from token_bucket import Limiter, MemoryStorage

from posthog.api import capture
from posthog.api.capture import (
    LIKELY_ANONYMOUS_IDS,
    get_distinct_id,
    is_randomly_partitioned,
)
from posthog.api.test.mock_sentry import mock_sentry_context_for_tagging
from posthog.api.test.openapi_validation import validate_response
from posthog.kafka_client.client import KafkaProducer, sessionRecordingKafkaProducer
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
)
from posthog.settings import (
    DATA_UPLOAD_MAX_MEMORY_SIZE,
    KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC,
)
from posthog.test.base import BaseTest


def mocked_get_ingest_context_from_token(_: Any) -> None:
    raise Exception("test exception")


parser = ResolvingParser(
    url=str(pathlib.Path(__file__).parent / "../../../openapi/capture.yaml"),
    strict=True,
)
openapi_spec = cast(Dict[str, Any], parser.specification)


large_data_array = [
    random.choice(string.ascii_letters) for _ in range(700 * 1024)
]  # 512 * 1024 is the max size of a single message and random letters shouldn't be compressible, so this should be at least 2 messages


class TestCapture(BaseTest):
    """
    Tests all data capture endpoints (e.g. `/capture` `/batch/`).
    We use Django's base test class instead of DRF's because we need granular control over the Content-Type sent over.
    """

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        # it is really important to know that /capture is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)

    def _to_json(self, data: Union[Dict, List]) -> str:
        return json.dumps(data)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _dict_from_b64(self, data: str) -> dict:
        return json.loads(base64.b64decode(data))

    def _to_arguments(self, patch_process_event_with_plugins: Any) -> dict:
        args = patch_process_event_with_plugins.call_args[1]["data"]

        return {
            "uuid": args["uuid"],
            "distinct_id": args["distinct_id"],
            "ip": args["ip"],
            "site_url": args["site_url"],
            "data": json.loads(args["data"]),
            "token": args["token"],
            "now": args["now"],
            "sent_at": args["sent_at"],
        }

    def _send_session_recording_event(
        self,
        number_of_events=1,
        event_data={},
        snapshot_source=3,
        snapshot_type=1,
        session_id="abc123",
        window_id="def456",
        distinct_id="ghi789",
        timestamp=1658516991883,
    ) -> dict:
        event = {
            "event": "$snapshot",
            "properties": {
                "$snapshot_data": {
                    "type": snapshot_type,
                    "data": {"source": snapshot_source, "data": event_data},
                    "timestamp": timestamp,
                },
                "$session_id": session_id,
                "$window_id": window_id,
                "distinct_id": distinct_id,
            },
            "offset": 1993,
        }

        self.client.post(
            "/s/",
            data={
                "data": json.dumps([event for _ in range(number_of_events)]),
                "api_key": self.team.api_token,
            },
        )

        return event

    def test_is_randomly_parititoned(self):
        """Test is_randomly_partitioned under local configuration."""
        distinct_id = 100
        override_key = f"{self.team.pk}:{distinct_id}"

        assert is_randomly_partitioned(override_key) is False

        with self.settings(EVENT_PARTITION_KEYS_TO_OVERRIDE=[override_key]):
            assert is_randomly_partitioned(override_key) is True

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_randomly_partitions_with_likely_anonymous_ids(self, kafka_produce):
        """Test is_randomly_partitioned in the prescence of likely anonymous ids."""
        for distinct_id in LIKELY_ANONYMOUS_IDS:
            data = {
                "event": "$autocapture",
                "properties": {
                    "distinct_id": distinct_id,
                    "token": self.team.api_token,
                },
            }
            with self.assertNumQueries(0):  # Capture does not hit PG anymore
                self.client.get(
                    "/e/?data=%s" % quote(self._to_json(data)),
                    HTTP_ORIGIN="https://localhost",
                )

            kafka_produce.assert_called_with(topic=KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, data=ANY, key=None)

    def test_cached_is_randomly_partitioned(self):
        """Assert the behavior of is_randomly_partitioned under certain cache settings.

        Setup for this test requires reloading the capture module as we are patching
        the cache parameters for testing. In particular, we are tightening the cache
        settings to test the behavior of is_randomly_partitioned.
        """
        distinct_id = 100
        partition_key = f"{self.team.pk}:{distinct_id}"
        limiter = Limiter(
            rate=1,
            capacity=1,
            storage=MemoryStorage(),
        )
        start = datetime.utcnow()

        with patch("posthog.api.capture.LIMITER", new=limiter):
            with freeze_time(start):
                # First time we see this key it's looked up in local config.
                # The bucket has capacity to serve 1 requests/key, so we are not immediately returning.
                # Since local config is empty and bucket has capacity, this should not override.
                with self.settings(
                    EVENT_PARTITION_KEYS_TO_OVERRIDE=[],
                    PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED=True,
                ):
                    assert capture.is_randomly_partitioned(partition_key) is False
                    assert limiter._storage._buckets[partition_key][0] == 0

                    # The second time we see the key we will have reached the capacity limit of the bucket (1).
                    # Without looking at the configuration we immediately return that we should randomly partition.
                    # Notice time is frozen so the bucket hasn't been replentished.
                    assert capture.is_randomly_partitioned(partition_key) is True

            with freeze_time(start + timedelta(seconds=1)):
                # Now we have let one second pass so the bucket must have capacity to serve the request.
                # We once again look at the local configuration, which is empty.
                with self.settings(
                    EVENT_PARTITION_KEYS_TO_OVERRIDE=[],
                    PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED=True,
                ):
                    assert capture.is_randomly_partitioned(partition_key) is False

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event(self, kafka_produce):
        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }
        with self.assertNumQueries(0):  # Capture does not hit PG anymore
            response = self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)),
                HTTP_ORIGIN="https://localhost",
            )

        self.assertEqual(response.get("access-control-allow-origin"), "https://localhost")
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": data,
                "token": self.team.api_token,
            },
            self._to_arguments(kafka_produce),
        )
        log_context = structlog.contextvars.get_contextvars()
        assert "token" in log_context
        assert log_context["token"] == self.team.api_token

    @patch("axes.middleware.AxesMiddleware")
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_shortcircuits(self, kafka_produce, patch_axes):
        patch_axes.return_value.side_effect = Exception("Axes middleware should not be called")

        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }
        with self.assertNumQueries(0):
            response = self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)),
                HTTP_ORIGIN="https://localhost",
            )
        self.assertEqual(response.get("access-control-allow-origin"), "https://localhost")
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": data,
                "token": self.team.api_token,
            },
            self._to_arguments(kafka_produce),
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_too_large(self, kafka_produce):
        # There is a setting in Django, `DATA_UPLOAD_MAX_MEMORY_SIZE`, which
        # limits the size of the request body. An error is  raise, e.g. when we
        # try to read `django.http.request.HttpRequest.body` in the view. We
        # want to make sure this doesn't it is returned as a 413 error, not as a
        # 500, otherwise we have issues with setting up sensible monitoring that
        # is resilient to clients that send too much data.
        response = self.client.post(
            "/e/",
            data=20 * DATA_UPLOAD_MAX_MEMORY_SIZE * "x",
            HTTP_ORIGIN="https://localhost",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 413)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_events_503_on_kafka_produce_errors(self, kafka_produce):
        produce_future = FutureProduceResult(topic_partition=TopicPartition(KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC, 1))
        future = FutureRecordMetadata(
            produce_future=produce_future,
            relative_offset=0,
            timestamp_ms=0,
            checksum=0,
            serialized_key_size=0,
            serialized_value_size=0,
            serialized_header_size=0,
        )
        future.failure(KafkaError("Failed to produce"))
        kafka_produce.return_value = future
        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }

        response = self.client.get("/e/?data=%s" % quote(self._to_json(data)), HTTP_ORIGIN="https://localhost")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_ip(self, kafka_produce):
        data = {
            "event": "some_event",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?data=%s" % quote(self._to_json(data)),
            HTTP_X_FORWARDED_FOR="1.2.3.4",
            HTTP_ORIGIN="https://localhost",
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "ip": "1.2.3.4",
                "site_url": "http://testserver",
                "data": data,
                "token": self.team.api_token,
            },
            self._to_arguments(kafka_produce),
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_ipv6(self, kafka_produce):
        data = {
            "event": "some_event",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?data=%s" % quote(self._to_json(data)),
            HTTP_X_FORWARDED_FOR="2345:0425:2CA1:0000:0000:0567:5673:23b5",
            HTTP_ORIGIN="https://localhost",
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "ip": "2345:0425:2CA1:0000:0000:0567:5673:23b5",
                "site_url": "http://testserver",
                "data": data,
                "token": self.team.api_token,
            },
            self._to_arguments(kafka_produce),
        )

    # Regression test as Azure Gateway forwards ipv4 ips with a port number
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_ip_with_port(self, kafka_produce):
        data = {
            "event": "some_event",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?data=%s" % quote(self._to_json(data)),
            HTTP_X_FORWARDED_FOR="1.2.3.4:5555",
            HTTP_ORIGIN="https://localhost",
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "ip": "1.2.3.4",
                "site_url": "http://testserver",
                "data": data,
                "token": self.team.api_token,
            },
            self._to_arguments(kafka_produce),
        )

    @patch("posthog.api.capture.configure_scope")
    @patch("posthog.kafka_client.client._KafkaProducer.produce", MagicMock())
    def test_capture_event_adds_library_to_sentry(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        data = {
            "event": "$autocapture",
            "properties": {
                "$lib": "web",
                "$lib_version": "1.14.1",
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }
        with freeze_time(timezone.now()):
            self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)),
                HTTP_ORIGIN="https://localhost",
            )

        mock_set_tag.assert_has_calls([call("library", "web"), call("library.version", "1.14.1")])

    @patch("posthog.api.capture.configure_scope")
    @patch("posthog.kafka_client.client._KafkaProducer.produce", MagicMock())
    def test_capture_event_adds_unknown_to_sentry_when_no_properties_sent(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }
        with freeze_time(timezone.now()):
            self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)),
                HTTP_ORIGIN="https://localhost",
            )

        mock_set_tag.assert_has_calls([call("library", "unknown"), call("library.version", "unknown")])

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_multiple_events(self, kafka_produce):
        response = self.client.post(
            "/batch/",
            data={
                "data": json.dumps(
                    [
                        {
                            "event": "beep",
                            "properties": {
                                "distinct_id": "eeee",
                                "token": self.team.api_token,
                            },
                        },
                        {
                            "event": "boop",
                            "properties": {
                                "distinct_id": "aaaa",
                                "token": self.team.api_token,
                            },
                        },
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(kafka_produce.call_count, 2)

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_drops_performance_events(self, kafka_produce):
        self.client.post(
            "/batch/",
            data={
                "data": json.dumps(
                    [
                        {
                            "event": "$performance_event",
                            "properties": {
                                "distinct_id": "eeee",
                                "token": self.team.api_token,
                            },
                        },
                        {
                            "event": "boop",
                            "properties": {
                                "distinct_id": "aaaa",
                                "token": self.team.api_token,
                            },
                        },
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(kafka_produce.call_count, 1)
        assert "boop" in kafka_produce.call_args_list[0][1]["data"]["data"]

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_emojis_in_text(self, kafka_produce):
        self.team.api_token = "xp9qT2VLY76JJg"
        self.team.save()

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            "/batch/",
            data={
                "data": "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
            },
        )
        properties = json.loads(kafka_produce.call_args[1]["data"]["data"])["properties"]
        self.assertEqual(properties["$elements"][0]["$el_text"], "💻 Writing code")

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_js_gzip(self, kafka_produce):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        response = self.client.post(
            "/batch/?compression=gzip-js",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xadRKn\xdb0\x10\xbdJ@xi\xd9CY\xd6o[\xf7\xb3\xe8gS4\x8b\xa2\x10(r$\x11\xa6I\x81\xa2\xe4\x18A.\xd1\x0b\xf4 \xbdT\x8f\xd0a\x93&mQt\xd5\x15\xc9\xf7\xde\xbc\x19\xf0\xcd-\xc3\x05m`5;]\x92\xfb\xeb\x9a\x8d\xde\x8d\xe8\x83\xc6\x89\xd5\xb7l\xe5\xe8`\xaf\xb5\x9do\x88[\xb5\xde\x9d'\xf4\x04=\x1b\xbc;a\xc4\xe4\xec=\x956\xb37\x84\x0f!\x8c\xf5vk\x9c\x14fpS\xa8K\x00\xbeUNNQ\x1b\x11\x12\xfd\xceFb\x14a\xb0\x82\x0ck\xf6(~h\xd6,\xe8'\xed,\xab\xcb\x82\xd0IzD\xdb\x0c\xa8\xfb\x81\xbc8\x94\xf0\x84\x9e\xb5\n\x03\x81U\x1aA\xa3[\xf2;c\x1b\xdd\xe8\xf1\xe4\xc4\xf8\xa6\xd8\xec\x92\x16\x83\xd8T\x91\xd5\x96:\x85F+\xe2\xaa\xb44Gq\xe1\xb2\x0cp\x03\xbb\x1f\xf3\x05\x1dg\xe39\x14Y\x9a\xf3|\xb7\xe1\xb0[3\xa5\xa7\xa0\xad|\xa8\xe3E\x9e\xa5P\x89\xa2\xecv\xb2H k1\xcf\xabR\x08\x95\xa7\xfb\x84C\n\xbc\x856\xe1\x9d\xc8\x00\x92Gu\x05y\x0e\xb1\x87\xc2EK\xfc?^\xda\xea\xa0\x85i<vH\xf1\xc4\xc4VJ{\x941\xe2?Xm\xfbF\xb9\x93\xd0\xf1c~Q\xfd\xbd\xf6\xdf5B\x06\xbd`\xd3\xa1\x08\xb3\xa7\xd3\x88\x9e\x16\xe8#\x1b)\xec\xc1\xf5\x89\xf7\x14G2\x1aq!\xdf5\xebfc\x92Q\xf4\xf8\x13\xfat\xbf\x80d\xfa\xed\xcb\xe7\xafW\xd7\x9e\x06\xb5\xfd\x95t*\xeeZpG\x8c\r\xbd}n\xcfo\x97\xd3\xabqx?\xef\xfd\x8b\x97Y\x7f}8LY\x15\x00>\x1c\xf7\x10\x0e\xef\xf0\xa0P\xbdi3vw\xf7\x1d\xccN\xdf\x13\xe7\x02\x00\x00",
            content_type="text/plain",
        )

        self.assertEqual(kafka_produce.call_count, 1)

        data = json.loads(kafka_produce.call_args[1]["data"]["data"])
        self.assertEqual(data["event"], "my-event")
        self.assertEqual(data["properties"]["prop"], "💻 Writing code")

        validate_response(openapi_spec, response)

    @patch("gzip.decompress")
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_invalid_js_gzip_zlib_error(self, kafka_produce, gzip_decompress):
        """
        This was prompted by an event request that was resulting in the zlib
        error "invalid distance too far back". I couldn't easily generate such a
        string so I'm just mocking the raise the error explicitly.

        Note that gzip can raise BadGzipFile (from OSError), EOFError, and
        zlib.error: https://docs.python.org/3/library/gzip.html#gzip.BadGzipFile
        """
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        gzip_decompress.side_effect = zlib.error("Error -3 while decompressing data: invalid distance too far back")

        response = self.client.post(
            "/batch/?compression=gzip-js",
            # NOTE: this is actually valid, but we are mocking the gzip lib to raise
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xadRKn\xdb0\x10\xbdJ@xi\xd9CY\xd6o[\xf7\xb3\xe8gS4\x8b\xa2\x10(r$\x11\xa6I\x81\xa2\xe4\x18A.\xd1\x0b\xf4 \xbdT\x8f\xd0a\x93&mQt\xd5\x15\xc9\xf7\xde\xbc\x19\xf0\xcd-\xc3\x05m`5;]\x92\xfb\xeb\x9a\x8d\xde\x8d\xe8\x83\xc6\x89\xd5\xb7l\xe5\xe8`\xaf\xb5\x9do\x88[\xb5\xde\x9d'\xf4\x04=\x1b\xbc;a\xc4\xe4\xec=\x956\xb37\x84\x0f!\x8c\xf5vk\x9c\x14fpS\xa8K\x00\xbeUNNQ\x1b\x11\x12\xfd\xceFb\x14a\xb0\x82\x0ck\xf6(~h\xd6,\xe8'\xed,\xab\xcb\x82\xd0IzD\xdb\x0c\xa8\xfb\x81\xbc8\x94\xf0\x84\x9e\xb5\n\x03\x81U\x1aA\xa3[\xf2;c\x1b\xdd\xe8\xf1\xe4\xc4\xf8\xa6\xd8\xec\x92\x16\x83\xd8T\x91\xd5\x96:\x85F+\xe2\xaa\xb44Gq\xe1\xb2\x0cp\x03\xbb\x1f\xf3\x05\x1dg\xe39\x14Y\x9a\xf3|\xb7\xe1\xb0[3\xa5\xa7\xa0\xad|\xa8\xe3E\x9e\xa5P\x89\xa2\xecv\xb2H k1\xcf\xabR\x08\x95\xa7\xfb\x84C\n\xbc\x856\xe1\x9d\xc8\x00\x92Gu\x05y\x0e\xb1\x87\xc2EK\xfc?^\xda\xea\xa0\x85i<vH\xf1\xc4\xc4VJ{\x941\xe2?Xm\xfbF\xb9\x93\xd0\xf1c~Q\xfd\xbd\xf6\xdf5B\x06\xbd`\xd3\xa1\x08\xb3\xa7\xd3\x88\x9e\x16\xe8#\x1b)\xec\xc1\xf5\x89\xf7\x14G2\x1aq!\xdf5\xebfc\x92Q\xf4\xf8\x13\xfat\xbf\x80d\xfa\xed\xcb\xe7\xafW\xd7\x9e\x06\xb5\xfd\x95t*\xeeZpG\x8c\r\xbd}n\xcfo\x97\xd3\xabqx?\xef\xfd\x8b\x97Y\x7f}8LY\x15\x00>\x1c\xf7\x10\x0e\xef\xf0\xa0P\xbdi3vw\xf7\x1d\xccN\xdf\x13\xe7\x02\x00\x00",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Failed to decompress data. Error -3 while decompressing data: invalid distance too far back",
                code="invalid_payload",
            ),
        )
        self.assertEqual(kafka_produce.call_count, 0)

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_js_gzip_with_no_content_type(self, kafka_produce):
        "IE11 sometimes does not send content_type"

        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        self.client.post(
            "/batch/?compression=gzip-js",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xadRKn\xdb0\x10\xbdJ@xi\xd9CY\xd6o[\xf7\xb3\xe8gS4\x8b\xa2\x10(r$\x11\xa6I\x81\xa2\xe4\x18A.\xd1\x0b\xf4 \xbdT\x8f\xd0a\x93&mQt\xd5\x15\xc9\xf7\xde\xbc\x19\xf0\xcd-\xc3\x05m`5;]\x92\xfb\xeb\x9a\x8d\xde\x8d\xe8\x83\xc6\x89\xd5\xb7l\xe5\xe8`\xaf\xb5\x9do\x88[\xb5\xde\x9d'\xf4\x04=\x1b\xbc;a\xc4\xe4\xec=\x956\xb37\x84\x0f!\x8c\xf5vk\x9c\x14fpS\xa8K\x00\xbeUNNQ\x1b\x11\x12\xfd\xceFb\x14a\xb0\x82\x0ck\xf6(~h\xd6,\xe8'\xed,\xab\xcb\x82\xd0IzD\xdb\x0c\xa8\xfb\x81\xbc8\x94\xf0\x84\x9e\xb5\n\x03\x81U\x1aA\xa3[\xf2;c\x1b\xdd\xe8\xf1\xe4\xc4\xf8\xa6\xd8\xec\x92\x16\x83\xd8T\x91\xd5\x96:\x85F+\xe2\xaa\xb44Gq\xe1\xb2\x0cp\x03\xbb\x1f\xf3\x05\x1dg\xe39\x14Y\x9a\xf3|\xb7\xe1\xb0[3\xa5\xa7\xa0\xad|\xa8\xe3E\x9e\xa5P\x89\xa2\xecv\xb2H k1\xcf\xabR\x08\x95\xa7\xfb\x84C\n\xbc\x856\xe1\x9d\xc8\x00\x92Gu\x05y\x0e\xb1\x87\xc2EK\xfc?^\xda\xea\xa0\x85i<vH\xf1\xc4\xc4VJ{\x941\xe2?Xm\xfbF\xb9\x93\xd0\xf1c~Q\xfd\xbd\xf6\xdf5B\x06\xbd`\xd3\xa1\x08\xb3\xa7\xd3\x88\x9e\x16\xe8#\x1b)\xec\xc1\xf5\x89\xf7\x14G2\x1aq!\xdf5\xebfc\x92Q\xf4\xf8\x13\xfat\xbf\x80d\xfa\xed\xcb\xe7\xafW\xd7\x9e\x06\xb5\xfd\x95t*\xeeZpG\x8c\r\xbd}n\xcfo\x97\xd3\xabqx?\xef\xfd\x8b\x97Y\x7f}8LY\x15\x00>\x1c\xf7\x10\x0e\xef\xf0\xa0P\xbdi3vw\xf7\x1d\xccN\xdf\x13\xe7\x02\x00\x00",
            content_type="",
        )

        self.assertEqual(kafka_produce.call_count, 1)

        data = json.loads(kafka_produce.call_args[1]["data"]["data"])
        self.assertEqual(data["event"], "my-event")
        self.assertEqual(data["properties"]["prop"], "💻 Writing code")

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_invalid_gzip(self, kafka_produce):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        response = self.client.post(
            "/track?compression=gzip",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Failed to decompress data. Compressed file ended before the end-of-stream marker was reached",
                code="invalid_payload",
            ),
        )
        self.assertEqual(kafka_produce.call_count, 0)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_invalid_lz64(self, kafka_produce):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        response = self.client.post("/track?compression=lz64", data="foo", content_type="text/plain")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Failed to decompress data.",
                code="invalid_payload",
            ),
        )
        self.assertEqual(kafka_produce.call_count, 0)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_incorrect_padding(self, kafka_produce):
        response = self.client.get(
            "/e/?data=eyJldmVudCI6IndoYXRldmVmciIsInByb3BlcnRpZXMiOnsidG9rZW4iOiJ0b2tlbjEyMyIsImRpc3RpbmN0X2lkIjoiYXNkZiJ9fQ",
            content_type="application/json",
            HTTP_REFERER="https://localhost",
        )
        self.assertEqual(response.json()["status"], 1)
        data = json.loads(kafka_produce.call_args[1]["data"]["data"])
        self.assertEqual(data["event"], "whatevefr")

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_empty_request_returns_an_error(self, kafka_produce):
        """
        Empty requests that fail silently cause confusion as to whether they were successful or not.
        """

        # Empty GET
        response = self.client.get(
            "/e/?data=",
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(kafka_produce.call_count, 0)

        # Empty POST
        response = self.client.post("/e/", {}, content_type="application/json", HTTP_ORIGIN="https://localhost")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(kafka_produce.call_count, 0)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch(self, kafka_produce):
        data = {"type": "capture", "event": "user signed up", "distinct_id": "2"}
        self.client.post(
            "/batch/",
            data={"api_key": self.team.api_token, "batch": [data]},
            content_type="application/json",
        )
        arguments = self._to_arguments(kafka_produce)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "uuid": mock.ANY,
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data, "properties": {}},  # type: ignore
                "token": self.team.api_token,
            },
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch_with_invalid_event(self, kafka_produce):
        data = [
            {"type": "capture", "event": "event1", "distinct_id": "2"},
            {"type": "capture", "event": "event2"},  # invalid
            {"type": "capture", "event": "event3", "distinct_id": "2"},
            {"type": "capture", "event": "event4", "distinct_id": "2"},
            {"type": "capture", "event": "event5", "distinct_id": "2"},
        ]
        response = self.client.post(
            "/batch/",
            data={"api_key": self.team.api_token, "batch": data},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: All events must have the event field "distinct_id"!',
                code="invalid_payload",
            ),
        )
        self.assertEqual(kafka_produce.call_count, 0)

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch_with_dumped_json_data(self, kafka_produce):
        """Test batch rejects payloads that contained JSON dumped data.

        This could happen when request batch data is dumped before creating the data dictionary:

        .. code-block:: python

            batch = json.dumps([{"event": "$groupidentify", "distinct_id": "2", "properties": {}}])
            requests.post("/batch/", data={"api_key": "123", "batch": batch})

        Notice batch already points to a str as we called json.dumps on it before calling requests.post.
        This is an error as requests.post would call json.dumps itself on the data dictionary.

        Once we get the request, as json.loads does not recurse on strings, we load the batch as a string,
        instead of a list of dictionaries (events). We should report to the user that their data is not as
        expected.
        """
        data = json.dumps([{"event": "$groupidentify", "distinct_id": "2", "properties": {}}])
        response = self.client.post(
            "/batch/",
            data={"api_key": self.team.api_token, "batch": data},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Invalid payload: All events must be dictionaries not 'str'!",
                code="invalid_payload",
            ),
        )
        self.assertEqual(kafka_produce.call_count, 0)

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch_gzip_header(self, kafka_produce):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2"}],
        }

        response = self.client.generic(
            "POST",
            "/batch/",
            data=gzip.compress(json.dumps(data).encode()),
            content_type="application/json",
            HTTP_CONTENT_ENCODING="gzip",
        )

        arguments = self._to_arguments(kafka_produce)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "uuid": mock.ANY,
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "token": self.team.api_token,
            },
        )

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch_gzip_param(self, kafka_produce):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2"}],
        }

        self.client.generic(
            "POST",
            "/batch/?compression=gzip",
            data=gzip.compress(json.dumps(data).encode()),
            content_type="application/json",
        )

        arguments = self._to_arguments(kafka_produce)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "uuid": mock.ANY,
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "token": self.team.api_token,
            },
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_batch_lzstring(self, kafka_produce):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2"}],
        }

        response = self.client.generic(
            "POST",
            "/batch/",
            data=lzstring.LZString().compressToBase64(json.dumps(data)).encode(),
            content_type="application/json",
            HTTP_CONTENT_ENCODING="lz64",
        )

        arguments = self._to_arguments(kafka_produce)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "uuid": mock.ANY,
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "token": self.team.api_token,
            },
        )

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_lz64_with_emoji(self, kafka_produce):
        self.team.api_token = "KZZZeIpycLH-tKobLBET2NOg7wgJF2KqDL5yWU_7tZw"
        self.team.save()
        response = self.client.post(
            "/batch/",
            data="NoKABBYN4EQKYDc4DsAuMBcYaD4NwyLswA0MADgE4D2JcZqAlnAM6bQwAkFzWMAsgIYBjMAHkAymAAaRdgCNKAd0Y0WMAMIALSgFs40tgICuZMilQB9IwBsV61KhIYA9I4CMAJgDsAOgAMvry4YABw+oY4AJnBaFHrqnOjc7t5+foEhoXokfKjqyHw6KhFRMcRschSKNGZIZIx0FMgsQQBspYwCJihm6nB0AOa2LC4+AKw+bR1wXfJ04TlDzSGllnQyKvJwa8ur1TR1DSou/j56dMhKtGaz6wBeAJ4GQagALPJ8buo3I8iLevQFWBczVGIxGAGYPABONxeMGQlzEcJ0Rj0ZACczXbg3OCQgBCyFxAlxAE1iQBBADSAC0ANYAVT4NIAKmDRC4eAA5AwAMUYABkAJIAcQMPCouOeZCCAFotAA1cLNeR6SIIOgCOBXcKHDwjSFBNyQnzA95BZ7SnxuAQjFwuABmYKCAg8bh8MqBYLgzRcIzc0pcfDgfD4Pn9uv1huNPhkwxGegMFy1KmxeIJRNJlNpDOZrPZXN5gpFYpIEqlsoVStOyDo9D4ljMJjtNBMZBsdgcziSxwCwVCPkclgofTOAH5kHAAB6oAC8jirNbodYbcCbxjOfTM4QoWj4Z0Onm7aT70hI8TiG5q+0aiQCzV80nUfEYZkYlkENLMGxkcQoNJYdrrJRSkEegkDMJtsiMTU7TfPouDAUBIGwED6nOaUDAnaVXWGdwYBAABdYhUF/FAVGpKkqTgAUSDuAQ+QACWlVAKQoGQ+VxABRJk3A5YQ+g8eQ+gAKW5NwKQARwAET5EY7gAdTpMwPFQKllQAX2ICg7TtJQEjAMFQmeNSCKAA==",
            content_type="application/json",
            HTTP_CONTENT_ENCODING="lz64",
        )
        self.assertEqual(response.status_code, 200)
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["data"]["event"], "🤓")

        validate_response(openapi_spec, response)

    def test_batch_incorrect_token_shape(self):
        # Capture does not validate the token anymore, but runs some basic checks
        # on the token shape, returning 401s in that case.
        response = self.client.post(
            "/batch/",
            data={
                "api_key": {"some": "object"},
                "batch": [
                    {
                        "type": "capture",
                        "event": "user signed up",
                        "distinct_id": "whatever",
                    }
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            self.unauthenticated_response(
                "Provided API key is not valid: not_string",
                code="not_string",
            ),
        )

    def test_batch_token_not_set(self):
        response = self.client.post(
            "/batch/",
            data={
                "batch": [
                    {
                        "type": "capture",
                        "event": "user signed up",
                        "distinct_id": "whatever",
                    }
                ]
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            self.unauthenticated_response(
                "API key not provided. You can find your project API key in PostHog project settings.",
                code="missing_api_key",
            ),
        )

        validate_response(openapi_spec, response)

    @patch("statshog.defaults.django.statsd.incr")
    def test_batch_distinct_id_not_set(self, statsd_incr):
        response = self.client.post(
            "/batch/",
            data={
                "api_key": self.team.api_token,
                "batch": [{"type": "capture", "event": "user signed up"}],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: All events must have the event field "distinct_id"!',
                code="invalid_payload",
            ),
        )

        # endpoint success metric + missing ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "missing_distinct_id"}})

        validate_response(openapi_spec, response)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_engage(self, kafka_produce):
        self.client.get(
            "/engage/?data=%s"
            % quote(
                self._to_json(
                    {
                        "$set": {"$os": "Mac OS X"},
                        "$token": "token123",
                        "$distinct_id": 3,
                        "$device_id": "16fd4afae9b2d8-0fce8fe900d42b-39637c0e-7e9000-16fd4afae9c395",
                        "$user_id": 3,
                    }
                )
            ),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["data"]["event"], "$identify")
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        arguments.pop("data")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "uuid": mock.ANY,
                "distinct_id": "3",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "token": self.team.api_token,
            },
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_python_library(self, kafka_produce):
        self.client.post(
            "/track/",
            data={
                "data": self._dict_to_b64({"event": "$pageview", "properties": {"distinct_id": "eeee"}}),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["token"], self.team.api_token)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_base64_decode_variations(self, kafka_produce):
        base64 = "eyJldmVudCI6IiRwYWdldmlldyIsInByb3BlcnRpZXMiOnsiZGlzdGluY3RfaWQiOiJlZWVlZWVlZ8+lZWVlZWUifX0="
        dict = self._dict_from_b64(base64)
        self.assertDictEqual(
            dict,
            {"event": "$pageview", "properties": {"distinct_id": "eeeeeeegϥeeeee"}},
        )

        # POST with "+" in the base64
        self.client.post(
            "/track/",
            data={
                "data": base64,
                "api_key": self.team.api_token,
            },  # main difference in this test
        )
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["token"], self.team.api_token)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

        # POST with " " in the base64 instead of the "+"
        self.client.post(
            "/track/",
            data={
                "data": base64.replace("+", " "),
                "api_key": self.team.api_token,
            },  # main difference in this test
        )
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["token"], self.team.api_token)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_js_library_underscore_sent_at(self, kafka_produce):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        data = {
            "event": "movie played",
            "timestamp": tomorrow.isoformat(),
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?_=%s&data=%s" % (int(tomorrow_sent_at.timestamp()), quote(self._to_json(data))),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )

        arguments = self._to_arguments(kafka_produce)

        # right time sent as sent_at to process_event

        sent_at = datetime.fromisoformat(arguments["sent_at"])
        self.assertEqual(sent_at.tzinfo, tz.utc)

        timediff = sent_at.timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_long_distinct_id(self, kafka_produce):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        data = {
            "event": "movie played",
            "timestamp": tomorrow.isoformat(),
            "properties": {"distinct_id": "a" * 250, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?_=%s&data=%s" % (int(tomorrow_sent_at.timestamp()), quote(self._to_json(data))),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(len(arguments["distinct_id"]), 200)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_sent_at_field(self, kafka_produce):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        self.client.post(
            "/track",
            data={
                "sent_at": tomorrow_sent_at.isoformat(),
                "data": self._dict_to_b64(
                    {
                        "event": "$pageview",
                        "timestamp": tomorrow.isoformat(),
                        "properties": {"distinct_id": "eeee"},
                    }
                ),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )

        arguments = self._to_arguments(kafka_produce)
        sent_at = datetime.fromisoformat(arguments["sent_at"])
        # right time sent as sent_at to process_event
        timediff = sent_at.timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

    def test_incorrect_json(self):
        response = self.client.post(
            "/capture/",
            '{"event": "incorrect json with trailing comma",}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Invalid JSON: Expecting property name enclosed in double quotes: line 1 column 48 (char 47)",
                code="invalid_payload",
            ),
        )

        validate_response(openapi_spec, response)

    @patch("statshog.defaults.django.statsd.incr")
    def test_distinct_id_nan(self, statsd_incr):
        response = self.client.post(
            "/track/",
            data={
                "data": json.dumps([{"event": "beep", "properties": {"distinct_id": float("nan")}}]),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: Event field "distinct_id" should not be blank!',
                code="invalid_payload",
            ),
        )

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "invalid_distinct_id"}})

    @patch("statshog.defaults.django.statsd.incr")
    def test_distinct_id_set_but_null(self, statsd_incr):
        response = self.client.post(
            "/e/",
            data={
                "api_key": self.team.api_token,
                "type": "capture",
                "event": "user signed up",
                "distinct_id": None,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: Event field "distinct_id" should not be blank!',
                code="invalid_payload",
            ),
        )

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "invalid_distinct_id"}})

    @patch("statshog.defaults.django.statsd.incr")
    def test_event_name_missing(self, statsd_incr):
        response = self.client.post(
            "/e/",
            data={
                "api_key": self.team.api_token,
                "type": "capture",
                "event": "",
                "distinct_id": "a valid id",
            },
            content_type="application/json",
        )

        # An invalid distinct ID will not return an error code, instead we will capture an exception
        # and will not ingest the event
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "missing_event_name"}})

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_custom_uuid(self, kafka_produce) -> None:
        uuid = "01823e89-f75d-0000-0d4d-3d43e54f6de5"
        response = self.client.post(
            "/e/",
            data={
                "api_key": self.team.api_token,
                "event": "some_event",
                "distinct_id": "1",
                "uuid": uuid,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        arguments = self._to_arguments(kafka_produce)
        self.assertEqual(arguments["uuid"], uuid)
        self.assertEqual(arguments["data"]["uuid"], uuid)

    @patch("statshog.defaults.django.statsd.incr")
    def test_custom_uuid_invalid(self, statsd_incr) -> None:
        response = self.client.post(
            "/e/",
            data={
                "api_key": self.team.api_token,
                "event": "some_event",
                "distinct_id": "1",
                "uuid": "invalid_uuid",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: Event field "uuid" is not a valid UUID!',
                code="invalid_payload",
            ),
        )

        # endpoint success metric + invalid UUID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event_uuid")

    def test_handle_lacking_event_name_field(self):
        response = self.client.post(
            "/e/",
            data={
                "distinct_id": "abc",
                "properties": {"cost": 2},
                "api_key": self.team.api_token,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: All events must have the event name field "event"!',
                code="invalid_payload",
            ),
        )

    def test_handle_invalid_snapshot(self):
        response = self.client.post(
            "/e/",
            data={
                "event": "$snapshot",
                "distinct_id": "abc",
                "api_key": self.team.api_token,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: $snapshot events must contain property "$snapshot_data"!',
                code="invalid_payload",
            ),
        )

    @parameterized.expand(
        # zips request paths, and tracing headers. As well as constructing a meaningful name for the test
        (f"{headers[0]} tracing headers to {path[0]}", path[1], headers[1])
        for path in [
            ("events", "/e/?ip=1&_=1651741927805"),
            ("decide", "/decide/"),
            ("recordings", "/s/?ip=1&_=1651741927805"),
        ]
        for headers in [
            (
                "sentry",
                ["traceparent", "request-id", "Sentry-Trace", "Baggage"],
            ),
            (
                "aws",
                ["x-amzn-trace-id"],
            ),
            (
                "azure",
                ["traceparent", "request-id", "request-context"],
            ),
            (
                "gcp",
                ["x-cloud-trace-context"],
            ),
        ]
    )
    def test_cors_allows_tracing_headers(self, _: str, path: str, headers: List[str]) -> None:
        expected_headers = ",".join(["X-Requested-With", "Content-Type"] + headers)
        presented_headers = ",".join(headers + ["someotherrandomheader"])
        response = self.client.options(
            path,
            HTTP_ORIGIN="https://localhost",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=presented_headers,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Headers"] == expected_headers

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_legacy_recording_ingestion_data_sent_to_kafka(self, kafka_produce) -> None:
        session_id = "some_session_id"
        self._send_session_recording_event(session_id=session_id)
        self.assertEqual(kafka_produce.call_count, 1)
        kafka_topic_used = kafka_produce.call_args_list[0][1]["topic"]
        self.assertEqual(kafka_topic_used, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS)
        key = kafka_produce.call_args_list[0][1]["key"]
        self.assertEqual(key, session_id)

    @patch("posthog.models.utils.UUIDT", return_value="fake-uuid")
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    @freeze_time("2021-05-10")
    def test_legacy_recording_ingestion_compression_and_transformation(self, kafka_produce, _) -> None:
        self.maxDiff = None
        timestamp = 1658516991883
        session_id = "fake-session-id"
        distinct_id = "fake-distinct-id"
        window_id = "fake-window-id"
        snapshot_source = 8
        snapshot_type = 8
        event_data = {"foo": "bar"}
        self._send_session_recording_event(
            timestamp=timestamp,
            snapshot_source=snapshot_source,
            snapshot_type=snapshot_type,
            session_id=session_id,
            distinct_id=distinct_id,
            window_id=window_id,
            event_data=event_data,
        )
        self.assertEqual(kafka_produce.call_count, 1)
        self.assertEqual(
            kafka_produce.call_args_list[0][1]["topic"],
            KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
        )
        key = kafka_produce.call_args_list[0][1]["key"]
        self.assertEqual(key, session_id)
        data_sent_to_kafka = json.loads(kafka_produce.call_args_list[0][1]["data"]["data"])

        assert data_sent_to_kafka == {
            "event": "$snapshot_items",
            "properties": {
                "$snapshot_items": [
                    {
                        "type": snapshot_type,
                        "timestamp": timestamp,
                        "data": {"data": event_data, "source": snapshot_source},
                    }
                ],
                "$session_id": session_id,
                "$window_id": window_id,
                "distinct_id": distinct_id,
            },
            "offset": 1993,
        }

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_recording_ingestion_can_write_to_blob_ingestion_topic_with_usual_size_limit(self, kafka_produce) -> None:
        with self.settings(
            SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES=512,
        ):
            self._send_session_recording_event(event_data=large_data_array)
            topic_counter = Counter([call[1]["topic"] for call in kafka_produce.call_args_list])

            assert topic_counter == Counter({KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS: 1})

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_recording_ingestion_can_write_to_blob_ingestion_topic(self, kafka_produce) -> None:
        with self.settings(
            SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES=20480,
        ):
            self._send_session_recording_event(event_data=large_data_array)
            topic_counter = Counter([call[1]["topic"] for call in kafka_produce.call_args_list])

            assert topic_counter == Counter({KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS: 1})

    @patch("posthog.kafka_client.client.SessionRecordingKafkaProducer")
    def test_create_session_recording_kafka_with_expected_hosts(
        self,
        session_recording_producer_singleton_mock: MagicMock,
    ) -> None:
        with self.settings(
            KAFKA_HOSTS=["first.server:9092", "second.server:9092"],
            KAFKA_SECURITY_PROTOCOL="SASL_SSL",
            SESSION_RECORDING_KAFKA_HOSTS=[
                "another-server:9092",
                "a-fourth.server:9092",
            ],
            SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL="SSL",
            SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES=1234,
        ):
            # avoid logs from being printed because the mock is None
            session_recording_producer_singleton_mock.return_value = KafkaProducer()

            data = "example"
            self._send_session_recording_event(event_data=data)

            session_recording_producer_singleton_mock.assert_called_with(
                compression_type=None,
                kafka_hosts=[
                    "another-server:9092",
                    "a-fourth.server:9092",
                ],
                kafka_security_protocol="SSL",
                max_request_size=1234,
            )

    @patch("posthog.api.capture.sessionRecordingKafkaProducer")
    @patch("posthog.api.capture.KafkaProducer")
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_can_redirect_session_recordings_to_alternative_kafka(
        self,
        kafka_produce: MagicMock,
        default_kafka_producer_mock: MagicMock,
        session_recording_producer_factory_mock: MagicMock,
    ) -> None:
        with self.settings(
            KAFKA_HOSTS=["first.server:9092", "second.server:9092"],
            SESSION_RECORDING_KAFKA_HOSTS=[
                "another-server:9092",
                "a-fourth.server:9092",
            ],
        ):
            default_kafka_producer_mock.return_value = KafkaProducer()
            session_recording_producer_factory_mock.return_value = sessionRecordingKafkaProducer()

            data = "example"
            session_id = "test_can_redirect_session_recordings_to_alternative_kafka"
            self._send_session_recording_event(event_data=data, session_id=session_id)
            # session events don't get routed through the default kafka producer
            default_kafka_producer_mock.assert_not_called()
            session_recording_producer_factory_mock.assert_called()

            assert len(kafka_produce.call_args_list) == 1

            call_one = kafka_produce.call_args_list[0][1]
            assert call_one["key"] == session_id
            data_sent_to_recording_kafka = json.loads(call_one["data"]["data"])
            assert data_sent_to_recording_kafka["event"] == "$snapshot_items"
            assert len(data_sent_to_recording_kafka["properties"]["$snapshot_items"]) == 1

    def test_get_distinct_id_non_json_properties(self) -> None:
        with self.assertRaises(ValueError):
            get_distinct_id({"properties": "str"})

        with self.assertRaises(ValueError):
            get_distinct_id({"properties": 123})

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_can_override_attributes_important_in_replicator_exports(self, kafka_produce):
        # Check that for the values required to import historical data, we override appropriately.
        response = self.client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "event1",
                            "uuid": "017d37c1-f285-0000-0e8b-e02d131925dc",
                            "sent_at": "2020-01-01T00:00:00Z",
                            "distinct_id": "id1",
                            "timestamp": "2020-01-01T00:00:00Z",
                            "properties": {"token": self.team.api_token},
                        }
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        kafka_produce_call = kafka_produce.call_args_list[0].kwargs
        event_data = json.loads(kafka_produce_call["data"]["data"])

        self.assertDictContainsSubset(
            {
                "uuid": "017d37c1-f285-0000-0e8b-e02d131925dc",
                "sent_at": "2020-01-01T00:00:00Z",
                "timestamp": "2020-01-01T00:00:00Z",
                "event": "event1",
                "distinct_id": "id1",
            },
            event_data,
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    @pytest.mark.ee
    def test_quota_limits_ignored_if_disabled(self, kafka_produce) -> None:
        from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

        replace_limited_team_tokens(
            QuotaResource.RECORDINGS,
            {self.team.api_token: timezone.now().timestamp() + 10000},
        )
        replace_limited_team_tokens(
            QuotaResource.EVENTS,
            {self.team.api_token: timezone.now().timestamp() + 10000},
        )
        self._send_session_recording_event()
        self.assertEqual(kafka_produce.call_count, 1)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    @pytest.mark.ee
    def test_quota_limits(self, kafka_produce: MagicMock) -> None:
        from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

        def _produce_events():
            kafka_produce.reset_mock()
            self._send_session_recording_event()
            self.client.post(
                "/e/",
                data={
                    "data": json.dumps(
                        [
                            {
                                "event": "beep",
                                "properties": {
                                    "distinct_id": "eeee",
                                    "token": self.team.api_token,
                                },
                            },
                            {
                                "event": "boop",
                                "properties": {
                                    "distinct_id": "aaaa",
                                    "token": self.team.api_token,
                                },
                            },
                        ]
                    ),
                    "api_key": self.team.api_token,
                },
            )

        with self.settings(QUOTA_LIMITING_ENABLED=True):
            _produce_events()
            self.assertEqual(
                [c[1]["topic"] for c in kafka_produce.call_args_list],
                [
                    "session_recording_snapshot_item_events_test",
                    "events_plugin_ingestion_test",
                    "events_plugin_ingestion_test",
                ],
            )

            replace_limited_team_tokens(
                QuotaResource.EVENTS,
                {self.team.api_token: timezone.now().timestamp() + 10000},
            )
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 1)  # Only the recording event

            replace_limited_team_tokens(
                QuotaResource.RECORDINGS,
                {self.team.api_token: timezone.now().timestamp() + 10000},
            )
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 0)  # No events

            replace_limited_team_tokens(
                QuotaResource.RECORDINGS,
                {self.team.api_token: timezone.now().timestamp() - 10000},
            )
            replace_limited_team_tokens(
                QuotaResource.EVENTS,
                {self.team.api_token: timezone.now().timestamp() - 10000},
            )
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 3)  # All events as limit-until timestamp is in the past

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_historical_analytics_events(self, kafka_produce) -> None:
        """
        Based on an environment variable, TOKENS_HISTORICAL_DATA, we send data
        to the KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL topic.
        """
        with self.settings(TOKENS_HISTORICAL_DATA=[self.team.api_token]):
            self.client.post(
                "/e/",
                data={
                    "data": json.dumps(
                        {
                            "event": "$autocapture",
                            "properties": {
                                "distinct_id": 2,
                                "token": self.team.api_token,
                                "$elements": [
                                    {
                                        "tag_name": "a",
                                        "nth_child": 1,
                                        "nth_of_type": 2,
                                        "attr__class": "btn btn-sm",
                                    },
                                    {
                                        "tag_name": "div",
                                        "nth_child": 1,
                                        "nth_of_type": 2,
                                        "$el_text": "💻",
                                    },
                                ],
                            },
                        }
                    )
                },
            )
            self.assertEqual(kafka_produce.call_count, 1)
            self.assertEqual(
                kafka_produce.call_args_list[0][1]["topic"],
                KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
            )
