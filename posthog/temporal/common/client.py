import asyncio
import dataclasses
from typing import Any

from django.conf import settings as django_settings

import temporalio.converter
import temporalio.contrib.opentelemetry
from asgiref.sync import async_to_sync
from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)

# Bounded exponential backoff for the initial connection to the Temporal frontend.
# Workers boot before Temporal may be reachable (server restart, coordinated deploy,
# transient network blip), and a single un-retried connect crashes the pod into a
# crash-loop. With these values the worst case waits ~1+2+4+8+16+30+30 ≈ 91s across
# 8 attempts before giving up, which comfortably outlasts a typical restart/deploy.
# These are opt-in (see `create_worker`) so request-path callers keep failing fast
# rather than tying up a request worker for ~90s when Temporal is unreachable.
WORKER_CONNECT_MAX_ATTEMPTS = 8
WORKER_CONNECT_INITIAL_RETRY_DELAY = 1.0
WORKER_CONNECT_MAX_RETRY_DELAY = 30.0
WORKER_CONNECT_BACKOFF_COEFFICIENT = 2.0


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
    initial_retry_delay: float = WORKER_CONNECT_INITIAL_RETRY_DELAY,
    max_retry_delay: float = WORKER_CONNECT_MAX_RETRY_DELAY,
    backoff_coefficient: float = WORKER_CONNECT_BACKOFF_COEFFICIENT,
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

    target_host = f"{host}:{port}"
    attempt = 0
    while True:
        attempt += 1
        try:
            return await Client.connect(
                target_host,
                namespace=namespace,
                tls=tls,
                runtime=runtime,
                interceptors=[temporalio.contrib.opentelemetry.TracingInterceptor()],
                data_converter=data_converter,
            )
        except Exception as err:
            # The SDK raises a RuntimeError ("Failed client connect ...") when the frontend is
            # unreachable. Retry with bounded exponential backoff so a transient outage at boot
            # self-heals instead of crash-looping the pod.
            if attempt >= max_attempts:
                logger.exception(
                    "Failed to connect to Temporal after %d attempts, giving up",
                    attempt,
                    target_host=target_host,
                    namespace=namespace,
                )
                raise

            delay = min(max_retry_delay, initial_retry_delay * (backoff_coefficient ** (attempt - 1)))
            logger.warning(
                "Failed to connect to Temporal (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                max_attempts,
                delay,
                err,
                target_host=target_host,
                namespace=namespace,
            )
            await asyncio.sleep(delay)


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
