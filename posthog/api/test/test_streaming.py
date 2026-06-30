from collections.abc import Iterator
from http import HTTPStatus

from unittest import mock

from django.http import StreamingHttpResponse

from posthog.api.streaming import sse_streaming_response, streaming_response


def _gen() -> Iterator[bytes]:
    yield b"data: hello\n\n"


class TestSSEStreamingResponse:
    def test_releases_db_connections_before_streaming(self):
        idle = mock.Mock(in_atomic_block=False)
        with mock.patch("posthog.api.streaming.connections") as connections:
            connections.all.return_value = [idle]
            sse_streaming_response(_gen())
        connections.all.assert_called_once_with(initialized_only=True)
        idle.close.assert_called_once()

    def test_does_not_sever_connections_with_an_open_transaction(self):
        in_transaction = mock.Mock(in_atomic_block=True)
        with mock.patch("posthog.api.streaming.connections") as connections:
            connections.all.return_value = [in_transaction]
            sse_streaming_response(_gen())
        in_transaction.close.assert_not_called()

    def test_sets_event_stream_content_type_and_default_headers(self):
        response = sse_streaming_response(_gen())
        assert isinstance(response, StreamingHttpResponse)
        assert response.headers["Content-Type"] == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache, no-transform"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.status_code == HTTPStatus.OK

    def test_caller_headers_and_status_override_defaults(self):
        response = sse_streaming_response(
            _gen(),
            status=HTTPStatus.ACCEPTED,
            headers={"Cache-Control": "no-cache", "X-Custom": "1"},
        )
        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.headers["X-Custom"] == "1"


class TestStreamingResponse:
    def test_honors_content_type_and_does_not_inject_sse_headers(self):
        # Non-SSE callers (audio, proxies) rely on the general wrapper passing their
        # content_type through and NOT forcing the SSE-only proxy-buffering header.
        response = streaming_response(_gen(), content_type="audio/mpeg")
        assert response.headers["Content-Type"] == "audio/mpeg"
        assert "X-Accel-Buffering" not in response.headers
        assert response.status_code == HTTPStatus.OK
