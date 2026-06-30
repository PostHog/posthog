import logging
import dataclasses
from typing import Any

from django.conf import settings as django_settings

import tenacity
import structlog
import temporalio.converter
import temporalio.contrib.opentelemetry
from asgiref.sync import async_to_sync
from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec

logger = structlog.get_logger(__name__)


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

    client = await Client.connect(
        f"{host}:{port}",
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


async def async_connect_with_retries(
    max_attempts: int = 6,
    initial_interval_seconds: float = 1.0,
    max_interval_seconds: float = 30.0,
) -> Client:
    """Connect to Temporal, retrying transient failures with exponential backoff.

    The bare connect can raise transient transport errors (e.g. a DNS lookup that
    fails while the Temporal host's name isn't yet resolvable during a deploy). Those
    blips clear on their own, so retry rather than crash the caller.
    """

    async for attempt in tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(min=initial_interval_seconds, max=max_interval_seconds),
        # Transport-level connect failures (DNS lookup failures, connection refused) surface
        # as RuntimeError from the SDK Core bridge, or OSError from the socket layer.
        retry=tenacity.retry_if_exception_type((RuntimeError, OSError)),
        before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
        reraise=True,
    ):
        with attempt:
            return await async_connect()

    raise AssertionError("unreachable: AsyncRetrying either returns a client or reraises")
