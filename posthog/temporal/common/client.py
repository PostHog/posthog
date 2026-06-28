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

logger = get_write_only_logger()

# Bounded retry-with-backoff for the initial connection to the Temporal frontend.
# Workers boot before — or during a restart of — the Temporal frontend, so the first
# `Client.connect()` can hit a transient `ConnectionRefused`. Without retry a momentary
# blip crashes the whole worker process; these defaults wait out normal infra churn.
CONNECT_MAX_ATTEMPTS = 10
CONNECT_INITIAL_RETRY_DELAY_SECONDS = 1.0
CONNECT_MAX_RETRY_DELAY_SECONDS = 30.0
CONNECT_BACKOFF_COEFFICIENT = 2.0


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
    attempt = 0
    while True:
        attempt += 1
        try:
            return await Client.connect(
                target,
                namespace=namespace,
                tls=tls,
                runtime=runtime,
                interceptors=[temporalio.contrib.opentelemetry.TracingInterceptor()],
                data_converter=data_converter,
            )
        except Exception as err:
            if attempt >= CONNECT_MAX_ATTEMPTS:
                logger.exception(
                    "temporal_client_connect_failed",
                    target=target,
                    attempts=attempt,
                )
                raise

            delay = min(
                CONNECT_MAX_RETRY_DELAY_SECONDS,
                CONNECT_INITIAL_RETRY_DELAY_SECONDS * (CONNECT_BACKOFF_COEFFICIENT ** (attempt - 1)),
            )
            logger.warning(
                "temporal_client_connect_retry",
                target=target,
                attempt=attempt,
                max_attempts=CONNECT_MAX_ATTEMPTS,
                retry_in_seconds=round(delay, 1),
                error=str(err),
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
