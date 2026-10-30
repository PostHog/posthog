from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.db import DatabaseError

import grpc
from parameterized import parameterized
from personhog.service.v1.service_pb2_grpc import PersonHogServiceServicer, add_PersonHogServiceServicer_to_server

from posthog.personhog_client.client import PersonHogClient
from posthog.personhog_client.interceptor import (
    _RETRYABLE_CODES,
    RetryInterceptor,
    _MutableClientCallDetails,
    is_transient_rpc_error,
    semantic_refusal_reason,
)
from posthog.personhog_client.proto import GetPersonRequest, GetPersonResponse


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


def _make_rpc_error(
    status_code: grpc.StatusCode,
    details: str | None = None,
    trailing_metadata: tuple[tuple[str, str], ...] = (),
) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = MagicMock(return_value=status_code)
    error.details = MagicMock(return_value=details)
    error.trailing_metadata = MagicMock(return_value=trailing_metadata)
    return error


def _make_ok_outcome() -> MagicMock:
    outcome = MagicMock()
    outcome.code.return_value = grpc.StatusCode.OK
    return outcome


def _make_transient_then_ok(
    fail_count: int,
    status_code: grpc.StatusCode,
    details: str | None = None,
    trailing_metadata: tuple[tuple[str, str], ...] = (),
):
    """Returns a continuation that fails fail_count times then succeeds."""
    calls: list[int] = []

    def continuation(details_, request):
        calls.append(1)
        if len(calls) <= fail_count:
            return _make_rpc_error(status_code, details, trailing_metadata)
        return _make_ok_outcome()

    return continuation, calls


def _make_always_failing(
    status_code: grpc.StatusCode,
    details: str | None = None,
    trailing_metadata: tuple[tuple[str, str], ...] = (),
):
    """Returns a continuation that always returns an error with the given status code."""
    calls: list[int] = []

    def continuation(details_, request):
        calls.append(1)
        return _make_rpc_error(status_code, details, trailing_metadata)

    return continuation, calls


class TestRetryInterceptorBehavior:
    def test_returns_on_first_success(self):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        ok_outcome = _make_ok_outcome()

        result = interceptor.intercept_unary_unary(lambda d, r: ok_outcome, details, request=b"")

        assert result is ok_outcome

    @parameterized.expand(
        [
            ("unavailable", grpc.StatusCode.UNAVAILABLE, ()),
            ("deadline_exceeded", grpc.StatusCode.DEADLINE_EXCEEDED, ()),
            ("aborted", grpc.StatusCode.ABORTED, ()),
            ("unknown", grpc.StatusCode.UNKNOWN, ()),
            ("unavailable_load_shed", grpc.StatusCode.UNAVAILABLE, (("x-not-applied", "load_shed"),)),
        ]
    )
    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_retries_transient_error_then_succeeds(
        self,
        _name: str,
        status_code: grpc.StatusCode,
        trailing_metadata: tuple[tuple[str, str], ...],
        mock_sleep,
    ):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_transient_then_ok(1, status_code, trailing_metadata=trailing_metadata)

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == grpc.StatusCode.OK
        assert len(calls) == 2
        assert mock_sleep.call_count == 1

    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_retries_internal_deserialization_failure_then_succeeds(self, mock_sleep):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_transient_then_ok(
            1, grpc.StatusCode.INTERNAL, details="Exception deserializing response!"
        )

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == grpc.StatusCode.OK
        assert len(calls) == 2
        assert mock_sleep.call_count == 1

    @parameterized.expand(
        [
            ("internal_db_error", grpc.StatusCode.INTERNAL, "deadlock detected", ()),
            (
                "db_timeout",
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Database lock_timeout: canceling statement due to lock timeout",
                (("x-db-timeout", "lock_timeout"),),
            ),
        ]
    )
    def test_does_not_retry_db_error(
        self,
        _name: str,
        status_code: grpc.StatusCode,
        error_details: str,
        trailing_metadata: tuple[tuple[str, str], ...],
    ):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(status_code, error_details, trailing_metadata)

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == status_code
        assert len(calls) == 1

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

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == status_code
        assert len(calls) == 1

    @patch("posthog.personhog_client.interceptor.time.sleep")
    def test_exhausts_retries_on_persistent_transient_error(self, mock_sleep):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(grpc.StatusCode.UNAVAILABLE)

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == grpc.StatusCode.UNAVAILABLE

        # 1 initial + 1 retry = 2 total attempts
        assert len(calls) == 2
        assert mock_sleep.call_count == 1

    def test_no_retries_when_max_retries_is_zero(self):
        interceptor = RetryInterceptor("test-client", max_retries=0, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()
        continuation, calls = _make_always_failing(grpc.StatusCode.UNAVAILABLE)

        result = interceptor.intercept_unary_unary(continuation, details, request=b"")

        assert result.code() == grpc.StatusCode.UNAVAILABLE
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

        interceptor.intercept_unary_unary(continuation, details, request=b"")

        mock_terminal.labels.assert_called_with(method="GetPerson", client="test-client", error_type="NotFound")
        mock_terminal.labels.return_value.inc.assert_called_once()
        mock_retries.labels.return_value.inc.assert_not_called()

    @patch("posthog.personhog_client.interceptor.PERSONHOG_RETRIES_TOTAL")
    @patch("posthog.personhog_client.interceptor.PERSONHOG_TERMINAL_ERRORS_TOTAL")
    def test_no_retry_or_terminal_metrics_on_success(self, mock_terminal, mock_retries):
        interceptor = RetryInterceptor("test-client", max_retries=1, initial_backoff_ms=1, max_backoff_ms=10)
        details = _make_call_details()

        interceptor.intercept_unary_unary(lambda d, r: _make_ok_outcome(), details, request=b"")

        mock_retries.labels.return_value.inc.assert_not_called()
        mock_terminal.labels.return_value.inc.assert_not_called()


class _FailsOncePersonHogService(PersonHogServiceServicer):
    def __init__(self, code: grpc.StatusCode, trailing_metadata: tuple[tuple[str, str], ...]) -> None:
        self._code = code
        self._trailing_metadata = trailing_metadata
        self.calls = 0

    def GetPerson(self, request, context):
        self.calls += 1
        if self.calls == 1:
            context.set_trailing_metadata(self._trailing_metadata)
            context.abort(self._code, "injected failure")
        return GetPersonResponse()


@contextmanager
def _client_for(service: PersonHogServiceServicer) -> Iterator[PersonHogClient]:
    with ThreadPoolExecutor(max_workers=1) as pool:
        server = grpc.server(pool)
        add_PersonHogServiceServicer_to_server(service, server)
        port = server.add_insecure_port("localhost:0")
        server.start()
        client = PersonHogClient(f"localhost:{port}", initial_backoff_ms=1, max_backoff_ms=1)
        try:
            yield client
        finally:
            client.close()
            server.stop(None)


class TestRetryInterceptorOnRealChannel:
    @parameterized.expand(
        [
            ("unavailable_is_retried", grpc.StatusCode.UNAVAILABLE, (), grpc.StatusCode.OK, 2),
            (
                "db_timeout_is_not_retried",
                grpc.StatusCode.DEADLINE_EXCEEDED,
                (("x-db-timeout", "lock_timeout"),),
                grpc.StatusCode.DEADLINE_EXCEEDED,
                1,
            ),
        ]
    )
    def test_retry_decision_through_the_client_interceptor_chain(
        self,
        _name: str,
        first_failure: grpc.StatusCode,
        trailing_metadata: tuple[tuple[str, str], ...],
        expected_code: grpc.StatusCode,
        expected_calls: int,
    ):
        service = _FailsOncePersonHogService(first_failure, trailing_metadata)

        with _client_for(service) as client:
            try:
                client.get_person(GetPersonRequest())
                code = grpc.StatusCode.OK
            except grpc.RpcError as exc:
                code = exc.code()

        assert (code, service.calls) == (expected_code, expected_calls)


def _wrapped_in_database_error(cause: BaseException) -> BaseException:
    wrapped = DatabaseError("personhog insert_cohort_members failed")
    wrapped.__cause__ = cause
    return wrapped


class TestIsTransientRpcError:
    @parameterized.expand(
        [
            ("retryable_code", _make_rpc_error(grpc.StatusCode.UNAVAILABLE), _RETRYABLE_CODES, True),
            ("terminal_code", _make_rpc_error(grpc.StatusCode.INVALID_ARGUMENT), _RETRYABLE_CODES, False),
            ("not_an_rpc_error", ValueError("boom"), _RETRYABLE_CODES, False),
            (
                "wrapped_retryable_cause",
                _wrapped_in_database_error(_make_rpc_error(grpc.StatusCode.UNAVAILABLE)),
                _RETRYABLE_CODES,
                True,
            ),
            (
                "code_outside_the_given_set",
                _make_rpc_error(grpc.StatusCode.RESOURCE_EXHAUSTED),
                _RETRYABLE_CODES,
                False,
            ),
            (
                "caller_supplied_codes",
                _make_rpc_error(grpc.StatusCode.RESOURCE_EXHAUSTED),
                {grpc.StatusCode.RESOURCE_EXHAUSTED},
                True,
            ),
            (
                "internal_deserialization_failure",
                _make_rpc_error(grpc.StatusCode.INTERNAL, details="Exception deserializing response!"),
                _RETRYABLE_CODES,
                True,
            ),
            (
                "internal_unrelated_details",
                _make_rpc_error(grpc.StatusCode.INTERNAL, details="deadlock detected"),
                _RETRYABLE_CODES,
                False,
            ),
        ]
    )
    def test_classifies_transport_failures(self, _name: str, exc: BaseException, codes, expected: bool):
        assert is_transient_rpc_error(exc, codes=codes) is expected


_REFUSAL_TRAILER = (("x-semantic-refusal", "op_id_reused"),)


class TestSemanticRefusalReason:
    @parameterized.expand(
        [
            (
                "refusal",
                _make_rpc_error(grpc.StatusCode.FAILED_PRECONDITION, trailing_metadata=_REFUSAL_TRAILER),
                "op_id_reused",
            ),
            ("bare_failed_precondition", _make_rpc_error(grpc.StatusCode.FAILED_PRECONDITION), None),
            (
                "trailer_on_another_code",
                _make_rpc_error(grpc.StatusCode.UNAVAILABLE, trailing_metadata=_REFUSAL_TRAILER),
                None,
            ),
            (
                "wrapped_refusal",
                _wrapped_in_database_error(
                    _make_rpc_error(grpc.StatusCode.FAILED_PRECONDITION, trailing_metadata=_REFUSAL_TRAILER)
                ),
                "op_id_reused",
            ),
            ("not_an_rpc_error", ValueError("boom"), None),
        ]
    )
    def test_reads_the_refusal_slug(self, _name: str, exc: BaseException, expected: str | None):
        assert semantic_refusal_reason(exc) == expected
