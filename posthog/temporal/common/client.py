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


def build_temporal_target(host: str, port: int | str) -> str:
    """Build and validate the `host:port` target handed to the temporalio Rust bridge.

    The bridge accepts only a bare `host:port` and rejects anything else with an opaque
    `invalid target URL: invalid port number` error that names neither setting, so a config
    typo reads as a bridge bug. We validate here — the single point every `connect()` caller
    shares — and raise an error that names the offending TEMPORAL_HOST/TEMPORAL_PORT value.
    """
    normalized_host = host.strip()
    # Strip a scheme if the host carries one (e.g. "http://temporal", "grpc://temporal").
    if "://" in normalized_host:
        normalized_host = normalized_host.split("://", 1)[1]
    normalized_host = normalized_host.rstrip("/")

    if not normalized_host:
        raise ValueError(f"TEMPORAL_HOST is empty; expected a hostname but got {host!r}")

    # A host that already embeds a port yields "host:port:port". IPv6 literals are bracketed
    # ("[::1]"), so only a colon outside the brackets signals an embedded port.
    host_after_brackets = normalized_host.rsplit("]", 1)[-1] if normalized_host.startswith("[") else normalized_host
    if ":" in host_after_brackets:
        raise ValueError(
            f"TEMPORAL_HOST already includes a port ({host!r}); set the host without a port and use TEMPORAL_PORT"
        )

    try:
        port_number = int(str(port).strip())
    except (TypeError, ValueError):
        raise ValueError(f"TEMPORAL_PORT must be an integer but got {port!r}") from None

    if not 0 < port_number <= 65535:
        raise ValueError(f"TEMPORAL_PORT must be between 1 and 65535 but got {port!r}")

    return f"{normalized_host}:{port_number}"


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
        build_temporal_target(host, port),
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
