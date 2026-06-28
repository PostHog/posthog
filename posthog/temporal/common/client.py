import asyncio
import dataclasses
from typing import Any

from django.conf import settings as django_settings

import structlog
import temporalio.converter
import temporalio.contrib.opentelemetry
from asgiref.sync import async_to_sync
from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec

logger = structlog.get_logger()

# Bounded retry for the initial connect. A momentary DNS failure during a deploy
# or pod reschedule (before the Temporal service's DNS entry resolves) should not
# crash worker boot and force a full pod restart. We retry over a short capped
# window and then give up so a genuine misconfiguration still surfaces.
#
# This is opt-in via `max_attempts` because `connect()` is also used on request
# paths (e.g. starting a workflow from an API view) where blocking for the full
# retry window on a real outage would be worse than failing fast. Worker boot
# passes the multi-attempt count; everything else keeps the fail-fast default.
CONNECT_MAX_ATTEMPTS = 10
CONNECT_INITIAL_BACKOFF_SECONDS = 0.5
CONNECT_MAX_BACKOFF_SECONDS = 5.0


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
    max_attempts: int = 1,
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

    target = f"{host}:{port}"
    backoff = CONNECT_INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_attempts + 1):
        try:
            client = await Client.connect(
                target,
                namespace=namespace,
                tls=tls,
                runtime=runtime,
                interceptors=[temporalio.contrib.opentelemetry.TracingInterceptor()],
                data_converter=data_converter,
            )
            return client
        except RuntimeError as e:
            # The gRPC bridge raises RuntimeError for connection failures, including the
            # transient "dns error ... Name or service not known" seen during rollouts.
            if attempt >= max_attempts:
                logger.exception(
                    "Failed to connect to Temporal after retries",
                    target=target,
                    namespace=namespace,
                    attempts=attempt,
                )
                raise
            logger.warning(
                "Failed to connect to Temporal, retrying with backoff",
                target=target,
                namespace=namespace,
                attempt=attempt,
                max_attempts=max_attempts,
                backoff_seconds=backoff,
                error=str(e),
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, CONNECT_MAX_BACKOFF_SECONDS)

    # Unreachable: the loop either returns a client or raises on the final attempt.
    raise RuntimeError(f"Failed to connect to Temporal at {target}")


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
