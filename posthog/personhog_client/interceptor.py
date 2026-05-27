from __future__ import annotations

import time
import contextvars
from collections import namedtuple
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

import grpc
from prometheus_client import Counter, Histogram

from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG

_ClientCallDetails = namedtuple(
    "_ClientCallDetails",
    ["method", "timeout", "metadata", "credentials", "wait_for_ready", "compression"],
)


class _MutableClientCallDetails(_ClientCallDetails, grpc.ClientCallDetails):
    pass


# ── Caller-tag context propagation ───────────────────────────────────

_caller_tag: contextvars.ContextVar[str] = contextvars.ContextVar("personhog_caller_tag", default="unknown")


@contextmanager
def personhog_caller_tag(tag: str) -> Generator[None, None, None]:
    token = _caller_tag.set(tag)
    try:
        yield
    finally:
        _caller_tag.reset(token)


def set_caller_tag(tag: str) -> contextvars.Token[str]:
    return _caller_tag.set(tag)


def get_caller_tag() -> str:
    return _caller_tag.get()


# ── Prometheus metrics ───────────────────────────────────────────────

PERSONHOG_DJANGO_REQUEST_DURATION = Histogram(
    "personhog_django_grpc_request_duration_seconds",
    "gRPC request duration from a Django personhog client to the personhog service",
    labelnames=["method", "client_name", "caller_tag"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

PERSONHOG_DJANGO_REQUEST_COUNT = Counter(
    "personhog_django_grpc_requests_total",
    "Total gRPC requests from a Django personhog client to the personhog service",
    labelnames=["method", "status", "client_name", "caller_tag"],
)

PERSONHOG_DJANGO_TIMEOUT_TOTAL = Counter(
    "personhog_django_grpc_timeouts_total",
    "gRPC requests that exceeded their deadline (DEADLINE_EXCEEDED)",
    labelnames=["method", "client_name"],
)


def _method_name(client_call_details: grpc.ClientCallDetails) -> str:
    # client_call_details.method is like "/personhog.service.v1.PersonHogService/GetPerson"
    method: str = client_call_details.method or "unknown"
    return method.rsplit("/", 1)[-1]


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
        new_details = _with_metadata(client_call_details, [("x-client-name", self._client_name)])
        return continuation(new_details, request)


class CallerTagInterceptor(grpc.UnaryUnaryClientInterceptor):
    """Injects x-caller-tag gRPC metadata header from the contextvars-based caller tag."""

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        tag = _caller_tag.get()
        new_details = _with_metadata(client_call_details, [("x-caller-tag", tag)])
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
        caller_tag = _caller_tag.get()
        start = time.monotonic()
        try:
            response = continuation(client_call_details, request)
            # grpc-python returns a future-like object; .code() is None on success
            code = response.code()
            status = code.name if code else "OK"
            PERSONHOG_DJANGO_REQUEST_COUNT.labels(
                method=method, status=status, client_name=self._client_name, caller_tag=caller_tag
            ).inc()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                PERSONHOG_DJANGO_TIMEOUT_TOTAL.labels(method=method, client_name=self._client_name).inc()
            return response
        except grpc.RpcError as exc:
            code = exc.code()
            status = code.name if code else "UNKNOWN"
            PERSONHOG_DJANGO_REQUEST_COUNT.labels(
                method=method, status=status, client_name=self._client_name, caller_tag=caller_tag
            ).inc()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                PERSONHOG_DJANGO_TIMEOUT_TOTAL.labels(method=method, client_name=self._client_name).inc()
            raise
        finally:
            PERSONHOG_DJANGO_REQUEST_DURATION.labels(
                method=method, client_name=self._client_name, caller_tag=caller_tag
            ).observe(time.monotonic() - start)
