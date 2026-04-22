from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

import grpc
from parameterized import parameterized

from posthog.personhog_client.interceptor import MetricsInterceptor, _MutableClientCallDetails


def _make_call_details(
    method: str = "/personhog.service.v1.PersonHogService/GetPerson",
    timeout: float = 5.0,
) -> grpc.ClientCallDetails:
    return _MutableClientCallDetails(
        method=method,
        timeout=timeout,
        metadata=None,
        credentials=None,
        wait_for_ready=None,
        compression=None,
    )


def _make_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.code.return_value = None
    return resp


def _make_error_response(status_code: grpc.StatusCode) -> MagicMock:
    resp = MagicMock()
    resp.code.return_value = status_code
    return resp


def _make_raising_continuation(status_code: grpc.StatusCode):
    def continuation(details, request):
        error = grpc.RpcError()
        error.code = MagicMock(return_value=status_code)
        raise error

    return continuation


class TestMetricsInterceptorReturnsBehavior:
    def test_returns_successful_response(self):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()
        ok_response = _make_ok_response()

        result = interceptor.intercept_unary_unary(lambda d, r: ok_response, details, request=b"")

        assert result is ok_response

    @parameterized.expand(
        [
            ("unavailable", grpc.StatusCode.UNAVAILABLE),
            ("internal", grpc.StatusCode.INTERNAL),
            ("not_found", grpc.StatusCode.NOT_FOUND),
        ]
    )
    def test_returns_non_ok_response(self, _name: str, status_code: grpc.StatusCode):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()
        error_response = _make_error_response(status_code)

        result = interceptor.intercept_unary_unary(lambda d, r: error_response, details, request=b"")

        assert result is error_response

    @parameterized.expand(
        [
            ("unavailable", grpc.StatusCode.UNAVAILABLE),
            ("internal", grpc.StatusCode.INTERNAL),
        ]
    )
    def test_propagates_rpc_error_exceptions(self, _name: str, status_code: grpc.StatusCode):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(_make_raising_continuation(status_code), details, request=b"")


class TestMetricsInterceptorTimeoutTracking:
    @patch("posthog.personhog_client.interceptor.PERSONHOG_DJANGO_TIMEOUT_TOTAL")
    def test_increments_timeout_counter_on_deadline_exceeded_response(self, mock_timeout_counter):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()
        response = _make_error_response(grpc.StatusCode.DEADLINE_EXCEEDED)

        interceptor.intercept_unary_unary(lambda d, r: response, details, request=b"")

        mock_timeout_counter.labels.assert_called_with(method="GetPerson", client_name="test-client")
        mock_timeout_counter.labels.return_value.inc.assert_called_once()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_DJANGO_TIMEOUT_TOTAL")
    def test_increments_timeout_counter_on_deadline_exceeded_exception(self, mock_timeout_counter):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(
                _make_raising_continuation(grpc.StatusCode.DEADLINE_EXCEEDED),
                details,
                request=b"",
            )

        mock_timeout_counter.labels.assert_called_with(method="GetPerson", client_name="test-client")
        mock_timeout_counter.labels.return_value.inc.assert_called_once()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_DJANGO_TIMEOUT_TOTAL")
    def test_does_not_increment_timeout_counter_on_other_errors(self, mock_timeout_counter):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()
        response = _make_error_response(grpc.StatusCode.UNAVAILABLE)

        interceptor.intercept_unary_unary(lambda d, r: response, details, request=b"")

        mock_timeout_counter.labels.return_value.inc.assert_not_called()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_DJANGO_TIMEOUT_TOTAL")
    def test_does_not_increment_timeout_counter_on_success(self, mock_timeout_counter):
        interceptor = MetricsInterceptor("test-client")
        details = _make_call_details()

        interceptor.intercept_unary_unary(lambda d, r: _make_ok_response(), details, request=b"")

        mock_timeout_counter.labels.return_value.inc.assert_not_called()
