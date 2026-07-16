import dataclasses
import collections.abc
from typing import Any

from django.conf import settings as django_settings

import temporalio.converter
import temporalio.contrib.opentelemetry
from asgiref.sync import async_to_sync
from temporalio.client import Client, Plugin, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec

# CPython's ThreadPoolExecutor.submit() raises RuntimeError with this exact message once the
# interpreter has begun shutting down. asgiref's async_to_sync drives its coroutine through such
# an executor, so sync_connect() hits it when a gunicorn worker gets SIGTERM while a request is
# still in flight.
_INTERPRETER_SHUTDOWN_MESSAGE = "cannot schedule new futures after interpreter shutdown"


class WorkerShuttingDownError(RuntimeError):
    """Raised when a synchronous Temporal connection is attempted during interpreter shutdown.

    This is an expected, self-healing shutdown race — not a bug worth reporting to error tracking.
    Subclasses RuntimeError so existing ``except RuntimeError`` handlers keep catching it.
    """


async def connect(
    host: str,
    port: int | str,
    namespace: str,
    client_cert: str | None = None,
    client_key: str | None = None,
    runtime: Runtime | None = None,
    server_root_ca_cert: str | None = None,
    settings: Any | None = django_settings,
    use_pydantic_converter: bool = False,
    add_otel_tracing_interceptor: bool = True,
    plugins: collections.abc.Sequence[Plugin] = (),
) -> Client:
    tls: TLSConfig | bool = False
    if client_cert and client_key:
        tls = TLSConfig(
            client_cert=bytes(client_cert, "utf-8"),
            client_private_key=bytes(client_key, "utf-8"),
        )

        if server_root_ca_cert:
            tls.server_root_ca_cert = bytes(server_root_ca_cert, "utf-8")

    data_converter = pydantic_data_converter if use_pydantic_converter else temporalio.converter.default()

    if settings is not None:
        data_converter = dataclasses.replace(
            data_converter,
            payload_codec=EncryptionCodec.from_settings(settings=settings),
        )

    # The classic TracingInterceptor injects trace context into workflow start headers (so a
    # caller's span becomes the parent of the workflow) AND creates spans for activity/workflow
    # execution on any worker built from this client. Worker processes disable it via
    # `add_otel_tracing_interceptor=False` because they trace execution through the
    # OpenTelemetryPlugin (passed via `plugins`) instead; leaving both on double-instruments
    # every activity and workflow. Non-worker callers (Django, Celery, the CLI, schedules) keep
    # it for start-context propagation.
    interceptors: list[temporalio.client.Interceptor] = []
    if add_otel_tracing_interceptor:
        interceptors.append(temporalio.contrib.opentelemetry.TracingInterceptor())

    client = await Client.connect(
        f"{host}:{port}",
        namespace=namespace,
        tls=tls,
        runtime=runtime,
        interceptors=interceptors,
        data_converter=data_converter,
        plugins=list(plugins),
    )
    return client


@async_to_sync
async def _sync_connect() -> Client:
    client = await connect(
        django_settings.TEMPORAL_HOST,
        django_settings.TEMPORAL_PORT,
        django_settings.TEMPORAL_NAMESPACE,
        django_settings.TEMPORAL_CLIENT_CERT,
        django_settings.TEMPORAL_CLIENT_KEY,
    )
    return client


def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    try:
        return _sync_connect()
    except RuntimeError as e:
        if _INTERPRETER_SHUTDOWN_MESSAGE in str(e):
            raise WorkerShuttingDownError(_INTERPRETER_SHUTDOWN_MESSAGE) from e
        raise


async def async_connect() -> Client:
    """Asynchronous connect to Temporal and return a Client."""
    client = await connect(
        django_settings.TEMPORAL_HOST,
        django_settings.TEMPORAL_PORT,
        django_settings.TEMPORAL_NAMESPACE,
        django_settings.TEMPORAL_CLIENT_CERT,
        django_settings.TEMPORAL_CLIENT_KEY,
    )
    return client
