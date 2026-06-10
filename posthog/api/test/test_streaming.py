from collections.abc import Iterator
from http import HTTPStatus

from unittest import mock

from django.http import StreamingHttpResponse

from posthog.api.streaming import sse_streaming_response


def _gen() -> Iterator[bytes]:
    yield b"data: hello\n\n"


class TestSSEStreamingResponse:
    def test_releases_db_connection_before_streaming(self):
        with mock.patch("posthog.api.streaming.close_old_connections") as release:
            sse_streaming_response(_gen())
        release.assert_called_once()

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
