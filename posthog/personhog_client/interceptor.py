from __future__ import annotations

import time
import random
from collections import namedtuple
from collections.abc import Sequence
from typing import Any

import grpc
import structlog
from prometheus_client import Counter, Histogram

from posthog.personhog_client.caller_tag import current_caller_tag
from posthog.personhog_client.metrics import (
    PERSONHOG_ERRORS_TOTAL,
    PERSONHOG_RETRIES_TOTAL,
    PERSONHOG_TERMINAL_ERRORS_TOTAL,
)
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG

logger = structlog.get_logger(__name__)

_ClientCallDetails = namedtuple(
    "_ClientCallDetails",
    ["method", "timeout", "metadata", "credentials", "wait_for_ready", "compression"],
)


class _MutableClientCallDetails(_ClientCallDetails, grpc.ClientCallDetails):
    pass


PERSONHOG_DJANGO_REQUEST_DURATION = Histogram(
    "personhog_django_grpc_request_duration_seconds",
    "gRPC request duration from a Django personhog client to the personhog service",
    labelnames=["method", "client_name"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

PERSONHOG_DJANGO_REQUEST_COUNT = Counter(
    "personhog_django_grpc_requests_total",
    "Total gRPC requests from a Django personhog client to the personhog service",
    labelnames=["method", "status", "client_name"],
)


def _method_name(client_call_details: grpc.ClientCallDetails) -> str:
    # client_call_details.method is like "/personhog.service.v1.PersonHogService/GetPerson"
    method: str = client_call_details.method or "unknown"
    return method.rsplit("/", 1)[-1]


def _grpc_error_type(code: grpc.StatusCode) -> str:
    """Convert a gRPC status code to PascalCase to match Node.js and Rust error_type labels."""
    # grpc.StatusCode.DEADLINE_EXCEEDED.name → "DEADLINE_EXCEEDED"
    # We need "DeadlineExceeded" to align with Code[error.code] in Node
    # and format!("{:?}", s.code()) in Rust.
    return code.name.replace("_", " ").title().replace(" ", "")


def _with_metadata(
    client_call_details: grpc.ClientCallDetails,
    extra: Sequence[tuple[str, str]],
) -> grpc.ClientCallDetails:
    metadata = list(client_call_details.metadata or []) + list(extra)
    return _MutableClientCallDetails(
        method=client_call_details.method,
        timeout=client_call_details.timeout,
        metadata=metadata,
        credentials=client_call_details.credentials,
        wait_for_ready=client_call_details.wait_for_ready,
        compression=client_call_details.compression,
    )


class ClientNameInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, client_name: str) -> None:
        self._client_name = client_name

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        new_details = _with_metadata(
            client_call_details,
            [("x-client-name", self._client_name), ("x-caller-tag", current_caller_tag())],
        )
        return continuation(new_details, request)


class ConsistencyHeaderInterceptor(grpc.UnaryUnaryClientInterceptor):
    """Sets x-read-consistency gRPC metadata header based on the request's read_options field.

    This allows the personhog-router to determine consistency level from
    headers without deserializing the request body.
    """

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        consistency = "eventual"
        try:
            if request.HasField("read_options") and request.read_options.consistency == CONSISTENCY_LEVEL_STRONG:
                consistency = "strong"
        except ValueError:
            pass
        new_details = _with_metadata(client_call_details, [("x-read-consistency", consistency)])
        return continuation(new_details, request)


class MetricsInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, client_name: str) -> None:
        self._client_name = client_name

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        method = _method_name(client_call_details)
        start = time.monotonic()
        try:
            response = continuation(client_call_details, request)
            # grpc-python returns a future-like object; .code() is None on success
            code = response.code()
            status = code.name if code else "OK"
            PERSONHOG_DJANGO_REQUEST_COUNT.labels(method=method, status=status, client_name=self._client_name).inc()
            if code is not None and code != grpc.StatusCode.OK:
                PERSONHOG_ERRORS_TOTAL.labels(
                    method=method, client=self._client_name, error_type=_grpc_error_type(code)
                ).inc()
            return response
        except grpc.RpcError as exc:
            code = exc.code()
            status = code.name if code else "UNKNOWN"
            error_type = _grpc_error_type(code) if code else "Unknown"
            PERSONHOG_DJANGO_REQUEST_COUNT.labels(method=method, status=status, client_name=self._client_name).inc()
            PERSONHOG_ERRORS_TOTAL.labels(method=method, client=self._client_name, error_type=error_type).inc()
            raise
        finally:
            PERSONHOG_DJANGO_REQUEST_DURATION.labels(method=method, client_name=self._client_name).observe(
                time.monotonic() - start
            )


_RETRYABLE_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.UNKNOWN,
    }
)


class RetryInterceptor(grpc.UnaryUnaryClientInterceptor):
    """Retries transient gRPC errors with jittered backoff.

    Covers four failure modes:
    - UNAVAILABLE: client-to-router connection failure
    - ABORTED: HTTP/2 stream reset during router deploys
    - DEADLINE_EXCEEDED: transient timeout (event loop saturation, brief backend slowness)
    - UNKNOWN: catch-all for transient failures that don't map to a specific code

    Sits outside MetricsInterceptor so each attempt gets its own per-call metrics.
    """

    def __init__(
        self, client_name: str, max_retries: int = 1, initial_backoff_ms: int = 50, max_backoff_ms: int = 1000
    ) -> None:
        self._client_name = client_name
        self._max_retries = max_retries
        self._initial_backoff_ms = initial_backoff_ms
        self._max_backoff_ms = max_backoff_ms

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        method = _method_name(client_call_details)
        attempt = 0
        delay_ms = self._initial_backoff_ms

        while True:
            try:
                return continuation(client_call_details, request)
            except grpc.RpcError as exc:
                code = exc.code()
                error_type = _grpc_error_type(code) if code else "Unknown"
                retryable = code in _RETRYABLE_CODES if code else False

                if not retryable or attempt == self._max_retries:
                    PERSONHOG_TERMINAL_ERRORS_TOTAL.labels(
                        method=method, client=self._client_name, error_type=error_type
                    ).inc()
                    raise

                PERSONHOG_RETRIES_TOTAL.labels(method=method, client=self._client_name, error_type=error_type).inc()

                logger.warning(
                    "personhog_grpc_retry",
                    method=method,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    error_type=error_type,
                )

                base = delay_ms / 2
                time.sleep((base + random.uniform(0, base)) / 1000)
                delay_ms = min(delay_ms * 2, self._max_backoff_ms)
                attempt += 1
