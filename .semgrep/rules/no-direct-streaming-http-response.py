# Test cases for no-direct-streaming-http-response rule
# ruff: noqa: F841, E501 — assignments exist solely to give semgrep something to match

from django.http import StreamingHttpResponse

from posthog.api.streaming import sse_streaming_response, streaming_response


def stream():
    yield b""


# ============================================================
# Should flag: direct construction
# ============================================================


def flag_bare_import():
    # ruleid: no-direct-streaming-http-response
    return StreamingHttpResponse(stream(), content_type="text/event-stream")


def flag_with_kwargs():
    # ruleid: no-direct-streaming-http-response
    response = StreamingHttpResponse(streaming_content=stream(), content_type="audio/mpeg")
    response["Cache-Control"] = "no-cache"
    return response


def flag_fully_qualified():
    import django.http

    # ruleid: no-direct-streaming-http-response
    return django.http.StreamingHttpResponse(stream(), content_type="text/event-stream")


# ============================================================
# Should NOT flag: using the wrappers, or annotation-only use
# ============================================================


def ok_streaming_response():
    # ok: no-direct-streaming-http-response
    return streaming_response(stream(), content_type="audio/mpeg")


def ok_sse_streaming_response():
    # ok: no-direct-streaming-http-response
    return sse_streaming_response(stream())


# ok: no-direct-streaming-http-response
def ok_return_annotation() -> StreamingHttpResponse:
    return sse_streaming_response(stream())
