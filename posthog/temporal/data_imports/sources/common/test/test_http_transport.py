import pytest
from unittest.mock import patch

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.sources.common.http.transport import (
    DEFAULT_RETRY,
    TrackedHTTPAdapter,
    make_tracked_adapter,
    make_tracked_session,
)


@pytest.fixture
def mock_record():
    with patch("posthog.temporal.data_imports.sources.common.http.transport.record_request") as m:
        yield m


def _fake_response(status_code: int = 200, body: bytes = b"ok") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = body
    resp.headers["Content-Length"] = str(len(body))
    return resp


@pytest.fixture
def fake_http_send():
    """Patch the parent `HTTPAdapter.send` so `TrackedHTTPAdapter.send()`'s `super().send()` returns a canned response without touching the network."""

    def _factory(response: Response):
        return patch.object(HTTPAdapter, "send", return_value=response)

    return _factory


def test_make_tracked_session_mounts_tracked_adapter_for_both_schemes():
    session = make_tracked_session()

    https_adapter = session.get_adapter("https://example.com/")
    http_adapter = session.get_adapter("http://example.com/")

    assert isinstance(https_adapter, TrackedHTTPAdapter)
    assert isinstance(http_adapter, TrackedHTTPAdapter)


def test_make_tracked_session_uses_default_retry():
    session = make_tracked_session()
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == DEFAULT_RETRY.total
    assert adapter.max_retries.backoff_factor == DEFAULT_RETRY.backoff_factor
    assert set(adapter.max_retries.status_forcelist or ()) == set(DEFAULT_RETRY.status_forcelist or ())


def test_make_tracked_session_honors_custom_retry():
    custom = Retry(total=7, backoff_factor=2.0, status_forcelist=(418,))
    session = make_tracked_session(retry=custom)
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == 7
    assert adapter.max_retries.backoff_factor == 2.0


def test_make_tracked_session_merges_headers():
    session = make_tracked_session(headers={"X-Source": "stripe", "User-Agent": "posthog/test"})

    assert session.headers["X-Source"] == "stripe"
    assert session.headers["User-Agent"] == "posthog/test"


def test_make_tracked_adapter_with_none_retry_uses_default():
    """`retry=None` is the explicit "use default" sentinel — not "disable retries"."""
    adapter = make_tracked_adapter(retry=None)

    # Should equal the DEFAULT_RETRY total
    assert adapter.max_retries.total == DEFAULT_RETRY.total


def test_send_records_request_for_2xx(mock_record, fake_http_send):
    session = make_tracked_session()

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        response = session.get("https://api.example.com/v1/ok")

    assert response.status_code == 200
    assert mock_record.call_count == 1
    args, kwargs = mock_record.call_args
    # First positional arg is the PreparedRequest, second is the Response.
    assert args[0].url == "https://api.example.com/v1/ok"
    assert args[1].status_code == 200
    assert kwargs["exception"] is None
    assert "started_at_monotonic" in kwargs


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 502, 503])
def test_send_records_request_for_non_2xx(mock_record, fake_http_send, status_code):
    session = make_tracked_session(retry=Retry(total=0))

    with fake_http_send(_fake_response(status_code=status_code, body=b"err")):
        response = session.get("https://api.example.com/v1/err")

    assert response.status_code == status_code
    assert mock_record.call_count == 1
    response_arg = mock_record.call_args.args[1]
    assert response_arg.status_code == status_code


def test_send_records_request_on_connection_exception(mock_record):
    """Network errors must still call record_request, and the exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))
    with pytest.raises(requests.exceptions.RequestException):
        # 127.0.0.1:1 is reserved/never-listening; resolves instantly with a connection refused.
        session.get("http://127.0.0.1:1/", timeout=2)

    assert mock_record.call_count == 1
    request_arg = mock_record.call_args.args[0]
    response_arg = mock_record.call_args.args[1]
    assert request_arg.url == "http://127.0.0.1:1/"
    assert response_arg is None
    assert mock_record.call_args.kwargs["exception"] is not None


def test_send_does_not_mask_real_outcome_when_record_raises(fake_http_send):
    """If record_request itself raises, the response must still be returned to the caller."""
    session = make_tracked_session()

    with (
        fake_http_send(_fake_response(status_code=200, body=b"ok")),
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport.record_request",
            side_effect=RuntimeError("observer broken"),
        ),
    ):
        # No exception should bubble up; the swallow happens inside `TrackedHTTPAdapter.send`'s `finally`.
        response = session.get("https://api.example.com/")

    assert response.status_code == 200


def test_send_does_not_mask_real_exception_when_record_raises():
    """If both the request fails AND the observer raises, the original exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))

    with patch(
        "posthog.temporal.data_imports.sources.common.http.transport.record_request",
        side_effect=RuntimeError("observer broken"),
    ):
        with pytest.raises(requests.exceptions.RequestException):
            session.get("http://127.0.0.1:1/", timeout=2)
