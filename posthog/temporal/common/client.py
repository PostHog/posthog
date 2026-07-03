import dataclasses
from typing import Any

from django.conf import settings as django_settings

import tenacity
import temporalio.converter
import temporalio.contrib.opentelemetry
from asgiref.sync import async_to_sync
from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger()

# Bounded retry for the initial connection to the Temporal frontend. Workers boot before the
# frontend is guaranteed reachable, so a transient ConnectionRefused / DNS-resolution failure from
# the Rust bridge would otherwise crash the process on startup. Retrying with backoff lets the
# worker ride out the brief unavailability instead.
CONNECT_MAX_ATTEMPTS = 10


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

    def _log_before_retry(retry_state: tenacity.RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "Failed to connect to Temporal, retrying",
            target=target,
            attempt=retry_state.attempt_number,
            max_attempts=CONNECT_MAX_ATTEMPTS,
            error=str(exc),
        )

    retryer = tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(CONNECT_MAX_ATTEMPTS),
        wait=tenacity.wait_random_exponential(multiplier=1, max=30),
        # The bridge surfaces ConnectionRefused / DNS-resolution failures as RuntimeError, and other
        # transient network issues as OSError. Both are worth riding out at boot.
        retry=tenacity.retry_if_exception_type((RuntimeError, OSError)),
        before_sleep=_log_before_retry,
        reraise=True,
    )
    client = await retryer(
        Client.connect,
        target,
        namespace=namespace,
        tls=tls,
        runtime=runtime,
        interceptors=[temporalio.contrib.opentelemetry.TracingInterceptor()],
        data_converter=data_converter,
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
