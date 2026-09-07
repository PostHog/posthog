from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

import grpc
from parameterized import parameterized

from posthog.personhog_client.interceptor import MetricsInterceptor, RetryInterceptor, _MutableClientCallDetails


def _successful_call():
    call = MagicMock(spec=grpc.Future)
    call.result.return_value = "ok"
    return call


def _make_call_details(
    method: str = "/personhog.service.v1.PersonHogService/GetPerson",
) -> grpc.ClientCallDetails:
    return _MutableClientCallDetails(
        method=method,
        timeout=5.0,
        metadata=None,
        credentials=None,
        wait_for_ready=None,
        compression=None,
    )


def _make_rpc_error(status_code: grpc.StatusCode) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = MagicMock(return_value=status_code)
    return error


def _make_transient_then_ok(fail_count: int, status_code: grpc.StatusCode):
    """Returns a continuation that fails fail_count times then succeeds."""
    calls: list[int] = []

    def continuation(details, request):
        calls.append(1)
        if len(calls) <= fail_count:
            raise _make_rpc_error(status_code)
        return _successful_call()

    return continuation, calls


def _make_always_failing(status_code: grpc.StatusCode):
    """Returns a continuation that always raises the given status code."""
    calls: list[int] = []

    def continuation(details, request):
        calls.append(1)
        raise _make_rpc_error(status_code)

    return continuation, calls


class TestRetryInterceptorBehavior:
    def test_returns_on_first_success(self):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()

        call = _successful_call()
        result = interceptor.intercept_unary_unary(lambda d, r: call, details, request=b"")

        assert result is call

    @parameterized.expand(
        [
            ("unavailable", grpc.StatusCode.UNAVAILABLE),
            ("deadline_exceeded", grpc.StatusCode.DEADLINE_EXCEEDED),
            ("aborted", grpc.StatusCode.ABORTED),
            ("unknown", grpc.StatusCode.UNKNOWN),
        ]
    )
    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_retries_transient_error_then_succeeds(self, _name: str, status_code: grpc.StatusCode, mock_sleep):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_transient_then_ok(1, status_code)

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.result() == "ok"
        assert len(calls) == 2
        assert mock_sleep.call_count == 1

    @parameterized.expand(
        [
            ("not_found", grpc.StatusCode.NOT_FOUND),
            ("invalid_argument", grpc.StatusCode.INVALID_ARGUMENT),
            ("permission_denied", grpc.StatusCode.PERMISSION_DENIED),
            ("unauthenticated", grpc.StatusCode.UNAUTHENTICATED),
            ("failed_precondition", grpc.StatusCode.FAILED_PRECONDITION),
            ("internal", grpc.StatusCode.INTERNAL),
            ("resource_exhausted", grpc.StatusCode.RESOURCE_EXHAUSTED),
        ]
    )
    def test_does_not_retry_non_retryable_error(self, _name: str, status_code: grpc.StatusCode):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(status_code)

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert len(calls) == 1

    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_exhausts_retries_on_persistent_transient_error(self, mock_sleep):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(grpc.StatusCode.UNAVAILABLE)

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(continuation, details, request=b"")

        # 1 initial + 1 retry = 2 total attempts
        assert len(calls) == 2
        assert mock_sleep.call_count == 1

    def test_no_retries_when_max_retries_is_zero(self):
        interceptor = RetryInterceptor("test-client", max_retries=0, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(grpc.StatusCode.UNAVAILABLE)

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert len(calls) == 1


class TestRetryInterceptorMetrics:
    @patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL")
    @patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL")
    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_emits_retry_metrics_per_attempt(self, mock_sleep, mock_terminal, mock_retries):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, _ = _make_transient_then_ok(1, grpc.StatusCode.UNAVAILABLE)

        interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert mock_retries.labels.return_value.inc.call_count == 1
        mock_retries.labels.assert_called_with(method="GetPerson", client="test-client", error_type="Unavailable")
        mock_terminal.labels.return_value.inc.assert_not_called()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL")
    @patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL")
    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_emits_terminal_metric_on_exhaustion(self, mock_sleep, mock_terminal, mock_retries):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, _ = _make_always_failing(grpc.StatusCode.UNAVAILABLE)

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(continuation, details, request=b"")

        mock_terminal.labels.assert_called_with(method="GetPerson", client="test-client", error_type="Unavailable")
        mock_terminal.labels.return_value.inc.assert_called_once()
        assert mock_retries.labels.return_value.inc.call_count == 1

    @patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL")
    @patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL")
    def test_emits_terminal_metric_on_non_retryable_error(self, mock_terminal, mock_retries):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, _ = _make_always_failing(grpc.StatusCode.NOT_FOUND)

        with pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(continuation, details, request=b"")

        mock_terminal.labels.assert_called_with(method="GetPerson", client="test-client", error_type="NotFound")
        mock_terminal.labels.return_value.inc.assert_called_once()
        mock_retries.labels.return_value.inc.assert_not_called()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL")
    @patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL")
    def test_no_retry_or_terminal_metrics_on_success(self, mock_terminal, mock_retries):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()

        interceptor.intercept_unary_unary(lambda d, r: _successful_call(), details, request=b"")

        mock_retries.labels.return_value.inc.assert_not_called()
        mock_terminal.labels.return_value.inc.assert_not_called()


@pytest.mark.parametrize(
    "method,code,failures,expected_attempts",
    [
        ("InsertCohortMembers", grpc.StatusCode.UNAVAILABLE, 1, 2),
        ("GetPersonsByUuids", grpc.StatusCode.UNKNOWN, 1, 2),
        ("CountCohortMembers", grpc.StatusCode.DEADLINE_EXCEEDED, 1, 2),
        ("InsertCohortMembers", grpc.StatusCode.ABORTED, 2, 2),
        ("InsertCohortMembers", grpc.StatusCode.PERMISSION_DENIED, 1, 1),
        ("SplitPerson", grpc.StatusCode.UNAVAILABLE, 1, 1),
    ],
)
def test_retries_real_grpc_outcomes(method, code, failures, expected_attempts):
    attempts = 0

    def handle(request, context):
        nonlocal attempts
        attempts += 1
        if attempts <= failures:
            context.abort(code, "Synthetic failure")
        context.set_trailing_metadata((("result", "complete"),))
        return request

    with ThreadPoolExecutor(max_workers=1) as executor:
        server = grpc.server(executor)
        server.add_generic_rpc_handlers(
            (
                grpc.method_handlers_generic_handler(
                    "test.Population", {method: grpc.unary_unary_rpc_method_handler(handle)}
                ),
            )
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            with (
                grpc.insecure_channel(f"127.0.0.1:{port}") as base,
                patch("posthog.personhog_client.interceptor.time.sleep"),
                patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL") as retries,
                patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL") as terminal,
            ):
                channel = grpc.intercept_channel(
                    base, RetryInterceptor("test-client"), MetricsInterceptor("test-client")
                )
                rpc = channel.unary_unary(f"/test.Population/{method}")
                if failures < expected_attempts:
                    response, call = rpc.with_call(b"members", timeout=5)
                    assert response == b"members"
                    assert ("result", "complete") in call.trailing_metadata()
                    terminal.labels.return_value.inc.assert_not_called()
                else:
                    with pytest.raises(grpc.RpcError) as error:
                        rpc(b"members", timeout=5)
                    assert error.value.code() == code
                    terminal.labels.return_value.inc.assert_called_once()
                assert attempts == expected_attempts
                assert retries.labels.return_value.inc.call_count == expected_attempts - 1
        finally:
            server.stop(0).wait()
