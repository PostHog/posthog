import json
import queue

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.test.client import Client

from rest_framework import status

from posthog.api.report_buffer import CSP_BUFFER_DROPPED, CSP_BUFFER_FAILED, CSP_BUFFER_SUBMITTED, CspReportBuffer


def _capture_result(ok=(), dropped=(), retried=(), unaccounted=(), warnings=()):
    return MagicMock(
        ok=list(ok),
        dropped=list(dropped),
        retried=list(retried),
        unaccounted=list(unaccounted),
        warnings=list(warnings),
        error=None,
    )


CSP_PAYLOAD = {
    "csp-report": {
        "document-uri": "https://example.com/foo/bar",
        "violated-directive": "default-src self",
        "effective-directive": "img-src",
        "original-policy": "default-src 'self'; img-src 'self' https://img.example.com",
        "disposition": "enforce",
        "blocked-uri": "https://evil.com/malicious-image.png",
    }
}


class TestCspReportBufferedView(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.client = Client(enforce_csrf_checks=True)

    @override_settings(CSP_REPORT_BUFFERED_FORWARD=True)
    @patch("posthog.api.report.capture_internal")
    @patch("posthog.api.report.csp_report_buffer")
    def test_buffered_mode_enqueues_instead_of_calling_capture(self, mock_buffer, mock_capture) -> None:
        resp = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(CSP_PAYLOAD),
            content_type="application/csp-report",
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert mock_capture.call_count == 0
        assert mock_buffer.enqueue.call_count == 1
        events = mock_buffer.enqueue.call_args.args[0]
        assert len(events) == 1
        assert mock_buffer.enqueue.call_args.kwargs["token"] == self.team.api_token

    @override_settings(CSP_REPORT_BUFFERED_FORWARD=True)
    @patch("posthog.api.report.csp_report_buffer")
    def test_buffered_mode_missing_token_returns_400_without_enqueue(self, mock_buffer) -> None:
        resp = self.client.post(
            "/report/",
            data=json.dumps(CSP_PAYLOAD),
            content_type="application/csp-report",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_buffer.enqueue.call_count == 0

    @patch("posthog.api.report.capture_internal")
    @patch("posthog.api.report.csp_report_buffer")
    def test_default_mode_stays_synchronous(self, mock_buffer, mock_capture) -> None:
        mock_capture.return_value = MagicMock(raise_for_status=MagicMock())
        resp = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(CSP_PAYLOAD),
            content_type="application/csp-report",
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert mock_capture.call_count == 1
        assert mock_buffer.enqueue.call_count == 0


class TestCspReportBufferLogic(SimpleTestCase):
    def _buffer(
        self,
        maxsize: int = 10,
        max_token_share: float = 1.0,
        max_bytes: int = 1_000_000,
        max_event_bytes: int = 100_000,
        flush_max_seconds: float = 5.0,
    ) -> CspReportBuffer:
        return CspReportBuffer(
            maxsize=maxsize,
            flush_interval=0.01,
            flush_max_events=100,
            flush_max_seconds=flush_max_seconds,
            max_token_share=max_token_share,
            max_bytes=max_bytes,
            max_event_bytes=max_event_bytes,
        )

    # _ensure_sender is patched out so no sender thread runs — collect/flush are driven synchronously.
    @patch.object(CspReportBuffer, "_ensure_sender")
    @patch("posthog.api.report_buffer.capture_batch_internal")
    def test_flush_groups_events_by_token(self, mock_capture, _mock_sender) -> None:
        mock_capture.return_value = _capture_result(ok=["u1"])
        buf = self._buffer()
        buf.enqueue([{"event": "a"}, {"event": "b"}], token="token-1")
        buf.enqueue([{"event": "c"}], token="token-2")

        buf._flush(buf._collect())

        assert mock_capture.call_count == 2
        calls = {call.kwargs["token"]: call.kwargs["events"] for call in mock_capture.call_args_list}
        assert [e["event"] for e in calls["token-1"]] == ["a", "b"]
        assert [e["event"] for e in calls["token-2"]] == ["c"]

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_enqueue_on_full_buffer_drops_oldest_without_blocking(self, _mock_sender) -> None:
        buf = self._buffer(maxsize=2)
        buf.enqueue([{"event": "a"}, {"event": "b"}], token="token-1")
        buf.enqueue([{"event": "c"}], token="token-2")

        remaining = [(t, e["event"]) for t, e, _ in (buf._queue.get_nowait() for _ in range(2))]
        assert remaining == [("token-1", "b"), ("token-2", "c")]
        with self.assertRaises(queue.Empty):
            buf._queue.get_nowait()

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_one_token_cannot_evict_other_tokens_events(self, _mock_sender) -> None:
        buf = self._buffer(maxsize=4, max_token_share=0.5)
        buf.enqueue([{"event": f"noisy-{i}"} for i in range(4)], token="token-noisy")
        buf.enqueue([{"event": "quiet-1"}, {"event": "quiet-2"}], token="token-quiet")

        contents = [buf._queue.get_nowait() for _ in range(4)]
        assert [e["event"] for t, e, _ in contents if t == "token-noisy"] == ["noisy-0", "noisy-1"]
        assert [e["event"] for t, e, _ in contents if t == "token-quiet"] == ["quiet-1", "quiet-2"]

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_collect_frees_token_share_for_new_events(self, _mock_sender) -> None:
        buf = self._buffer(maxsize=4, max_token_share=0.5)
        buf.enqueue([{"event": "a"}, {"event": "b"}, {"event": "c"}], token="token-1")
        assert len(buf._collect()) == 2

        buf.enqueue([{"event": "d"}], token="token-1")
        assert [e["event"] for _, e, _s in buf._collect()] == ["d"]

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_oversized_event_is_dropped(self, _mock_sender) -> None:
        buf = self._buffer(max_event_bytes=100)
        buf.enqueue([{"event": "big", "raw": "x" * 500}, {"event": "small"}], token="token-1")

        contents = [buf._queue.get_nowait() for _ in range(buf._queue.qsize())]
        assert [e["event"] for _, e, _s in contents] == ["small"]

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_bytes_stay_reserved_while_batch_in_flight(self, _mock_sender) -> None:
        buf = self._buffer(max_bytes=250, max_event_bytes=200)
        buf.enqueue([{"event": "0", "raw": "x" * 100}], token="token-1")
        in_flight = buf._collect()
        assert len(in_flight) == 1

        buf.enqueue([{"event": "1", "raw": "x" * 100}, {"event": "2", "raw": "x" * 100}], token="token-1")
        assert buf._queue.qsize() == 1

        buf._release_bytes(in_flight)
        buf.enqueue([{"event": "3", "raw": "x" * 100}], token="token-1")
        assert buf._queue.qsize() == 2

    @patch.object(CspReportBuffer, "_ensure_sender")
    @patch("posthog.api.report_buffer.capture_batch_internal")
    def test_partial_batch_failure_splits_submitted_and_failed(self, mock_capture, _mock_sender) -> None:
        mock_capture.return_value = _capture_result(ok=["u1"], dropped=["u2"])
        buf = self._buffer()
        submitted_before = CSP_BUFFER_SUBMITTED._value.get()
        failed_before = CSP_BUFFER_FAILED._value.get()

        buf._flush([("token-1", {"event": "a"}, 10), ("token-1", {"event": "b"}, 10)])

        assert CSP_BUFFER_SUBMITTED._value.get() - submitted_before == 1
        assert CSP_BUFFER_FAILED._value.get() - failed_before == 1

    @patch.object(CspReportBuffer, "_ensure_sender")
    def test_byte_budget_evicts_oldest(self, _mock_sender) -> None:
        buf = self._buffer(max_bytes=250, max_event_bytes=200)
        # Each event serializes to ~120 bytes, so the third pushes total over 250.
        events = [{"event": str(i), "raw": "x" * 100} for i in range(3)]
        buf.enqueue(events, token="token-1")

        contents = [buf._queue.get_nowait() for _ in range(buf._queue.qsize())]
        assert [e["event"] for _, e, _s in contents] == ["1", "2"]
        assert buf._total_bytes <= 250

    @patch("posthog.api.report_buffer.capture_exception")
    @patch("posthog.api.report_buffer.capture_batch_internal", side_effect=Exception("capture down"))
    def test_flush_failure_does_not_raise(self, mock_capture, mock_capture_exception) -> None:
        buf = self._buffer()
        buf._flush([("token-1", {"event": "a"}, 20)])
        assert mock_capture.call_count == 1
        assert mock_capture_exception.call_count == 1

    # Regression: token groups are submitted serially, so a flood of distinct
    # tokens against a slow capture-rs could stall the sender for the sum of
    # every group's transport budget while the queue evicted everything behind
    # it. The flush deadline must cut the loop and count unsent events.
    @patch("posthog.api.report_buffer.time.monotonic")
    @patch("posthog.api.report_buffer.capture_batch_internal")
    def test_flush_stops_at_deadline_and_drops_remaining_groups(self, mock_capture, mock_monotonic) -> None:
        mock_capture.return_value = _capture_result(ok=["u1"])
        # monotonic calls: deadline anchor (0.0), group-1 check (0.5, within
        # budget), group-2 check (10.0, past it) — groups 2 and 3 never submit.
        mock_monotonic.side_effect = [0.0, 0.5, 10.0]
        buf = self._buffer(flush_max_seconds=1.0)
        dropped_before = CSP_BUFFER_DROPPED.labels(reason="flush_deadline")._value.get()

        buf._flush(
            [
                ("token-1", {"event": "a"}, 10),
                ("token-2", {"event": "b"}, 10),
                ("token-2", {"event": "c"}, 10),
                ("token-3", {"event": "d"}, 10),
            ]
        )

        assert mock_capture.call_count == 1
        assert mock_capture.call_args.kwargs["token"] == "token-1"
        dropped = CSP_BUFFER_DROPPED.labels(reason="flush_deadline")._value.get() - dropped_before
        assert dropped == 3
