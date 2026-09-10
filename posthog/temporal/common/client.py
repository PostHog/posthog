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
async def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    client = await connect(
        django_settings.TEMPORAL_HOST,
        django_settings.TEMPORAL_PORT,
        django_settings.TEMPORAL_NAMESPACE,
        django_settings.TEMPORAL_CLIENT_CERT,
        django_settings.TEMPORAL_CLIENT_KEY,
    )
    return client


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
