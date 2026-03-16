from __future__ import annotations

import time
from collections import namedtuple
from collections.abc import Sequence
from typing import Any

import grpc
from prometheus_client import Counter, Histogram

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
            return response
        except grpc.RpcError as exc:
            status = exc.code().name if exc.code() else "UNKNOWN"
            PERSONHOG_DJANGO_REQUEST_COUNT.labels(method=method, status=status, client_name=self._client_name).inc()
            raise
        finally:
            PERSONHOG_DJANGO_REQUEST_DURATION.labels(method=method, client_name=self._client_name).observe(
                time.monotonic() - start
            )
