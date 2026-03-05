from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import grpc
from prometheus_client import Counter, Histogram

PERSONHOG_REQUEST_DURATION = Histogram(
    "personhog_grpc_request_duration_seconds",
    "gRPC request duration from the Django client to personhog",
    labelnames=["method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

PERSONHOG_REQUEST_COUNT = Counter(
    "personhog_grpc_requests_total",
    "Total gRPC requests from the Django client to personhog",
    labelnames=["method", "status"],
)


def _method_name(client_call_details: grpc.ClientCallDetails) -> str:
    # client_call_details.method is like "/personhog.service.v1.PersonHogService/GetPerson"
    method: str = client_call_details.method or "unknown"
    return method.rsplit("/", 1)[-1]


def _with_metadata(
    client_call_details: grpc.ClientCallDetails,
    extra: Sequence[tuple[str, str]],
) -> grpc.ClientCallDetails:
    existing = list(client_call_details.metadata) if client_call_details.metadata else []
    existing.extend(extra)
    return grpc.ClientCallDetails(
        method=client_call_details.method,
        timeout=client_call_details.timeout,
        metadata=existing,
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
            PERSONHOG_REQUEST_COUNT.labels(method=method, status=status).inc()
            return response
        except grpc.RpcError as exc:
            status = exc.code().name if exc.code() else "UNKNOWN"
            PERSONHOG_REQUEST_COUNT.labels(method=method, status=status).inc()
            raise
        finally:
            PERSONHOG_REQUEST_DURATION.labels(method=method).observe(time.monotonic() - start)
