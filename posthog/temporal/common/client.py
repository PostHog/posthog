import random
import asyncio
import logging
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

logger = logging.getLogger(__name__)

# A transient DNS or network blip makes Temporal's `Client.connect` raise a plain RuntimeError
# ("Temporary failure in name resolution", "Name or service not known"). Without a retry that
# error reaches every Django, Celery, CLI, and worker caller. Retry a few times with backoff so a
# blip clears itself; a real outage still raises after the attempts run out.
CONNECT_MAX_ATTEMPTS = 4
CONNECT_INITIAL_BACKOFF_SECONDS = 0.5
CONNECT_BACKOFF_MULTIPLIER = 2.0

# A blackholed Temporal address (dropped SYNs from a NetworkPolicy or security-group change,
# conntrack exhaustion, a node failure) leaves the TCP dial with nothing to bound it, so a single
# attempt can hang on the OS timeout for over two minutes and the retry loop would multiply that.
# Bound each attempt so the loop has a predictable ceiling and a stuck dial cannot pin a Django
# worker or startup process. Kept above the SDK's ~10s RPC retry window so a slow-but-healthy
# connect is not cut short.
CONNECT_ATTEMPT_TIMEOUT_SECONDS = 15.0


class TemporalConnectionError(RuntimeError):
    """Raised when connecting to Temporal fails after retries. Lets callers tell a transient
    network or DNS problem apart from a workflow or schedule error."""


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

    last_error: Exception | None = None
    backoff = CONNECT_INITIAL_BACKOFF_SECONDS
    for attempt in range(1, CONNECT_MAX_ATTEMPTS + 1):
        try:
            async with asyncio.timeout(CONNECT_ATTEMPT_TIMEOUT_SECONDS):
                return await Client.connect(
                    f"{host}:{port}",
                    namespace=namespace,
                    tls=tls,
                    runtime=runtime,
                    interceptors=interceptors,
                    data_converter=data_converter,
                    plugins=list(plugins),
                )
        # A timed-out attempt raises TimeoutError (an OSError subclass), so a stuck dial is caught
        # here and retried like any other transient blip.
        except (RuntimeError, OSError) as error:
            last_error = error
            if attempt == CONNECT_MAX_ATTEMPTS:
                break
            # Jitter spreads reconnects so callers do not retry in lockstep after a shared blip.
            delay = backoff * (1 + random.random())
            logger.warning(
                "Temporal connect failed (attempt %s/%s), retrying in %.2fs: %s",
                attempt,
                CONNECT_MAX_ATTEMPTS,
                delay,
                error,
            )
            await asyncio.sleep(delay)
            backoff *= CONNECT_BACKOFF_MULTIPLIER

    assert last_error is not None
    raise TemporalConnectionError(
        f"Could not connect to Temporal at {host}:{port} after {CONNECT_MAX_ATTEMPTS} attempts"
    ) from last_error


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
