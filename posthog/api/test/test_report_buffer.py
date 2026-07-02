import json
import queue

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.test.client import Client

from rest_framework import status

from posthog.api.report_buffer import CspReportBuffer

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
    def _buffer(self, maxsize: int = 10) -> CspReportBuffer:
        return CspReportBuffer(maxsize=maxsize, flush_interval=0.01, flush_max_events=100)

    # _ensure_sender is patched out so no sender thread runs — collect/flush are driven synchronously.
    @patch.object(CspReportBuffer, "_ensure_sender")
    @patch("posthog.api.report_buffer.capture_batch_internal")
    def test_flush_groups_events_by_token(self, mock_capture, _mock_sender) -> None:
        mock_capture.return_value = MagicMock(raise_for_status=MagicMock())
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
        buf.enqueue([{"event": "a"}, {"event": "b"}, {"event": "c"}], token="token-1")

        remaining = [buf._queue.get_nowait()[1]["event"] for _ in range(2)]
        assert remaining == ["b", "c"]
        with self.assertRaises(queue.Empty):
            buf._queue.get_nowait()

    @patch("posthog.api.report_buffer.capture_exception")
    @patch("posthog.api.report_buffer.capture_batch_internal", side_effect=Exception("capture down"))
    def test_flush_failure_does_not_raise(self, mock_capture, mock_capture_exception) -> None:
        buf = self._buffer()
        buf._flush([("token-1", {"event": "a"})])
        assert mock_capture.call_count == 1
        assert mock_capture_exception.call_count == 1
