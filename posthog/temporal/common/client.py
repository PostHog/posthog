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
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.codec import EncryptionCodec

logger = structlog.get_logger(__name__)

# gRPC status codes that indicate a transient server/connectivity problem rather than a
# permanent failure of the request itself — safe to retry or to treat as "leave state alone".
_TRANSIENT_RPC_STATUS_CODES = frozenset(
    {RPCStatusCode.UNAVAILABLE, RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.ABORTED}
)


def is_transient_temporal_error(error: BaseException) -> bool:
    """Whether an error from a Temporal call is a transient connectivity issue.

    `Client.connect` surfaces transport-level failures (e.g. a connection reset) as a
    `RuntimeError`, while in-flight RPCs raise `RPCError` carrying a gRPC status code. Both
    can be momentary blips that should not be treated as permanent failures by callers.
    """
    if isinstance(error, RuntimeError):
        return True
    if isinstance(error, RPCError):
        return error.status in _TRANSIENT_RPC_STATUS_CODES
    return False


# Bounded retry for the initial Temporal connection. A transient network blip (e.g. the
# server resetting the connection mid-handshake) surfaces from `Client.connect` as a
# `RuntimeError`, so we retry a few times with exponential backoff before giving up rather
# than letting a momentary reset propagate to callers.
CONNECT_MAX_ATTEMPTS = 4
CONNECT_INITIAL_RETRY_DELAY = 0.5
CONNECT_MAX_RETRY_DELAY = 4.0


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

    attempt = 0
    while True:
        try:
            return await Client.connect(
                f"{host}:{port}",
                namespace=namespace,
                tls=tls,
                runtime=runtime,
                interceptors=[temporalio.contrib.opentelemetry.TracingInterceptor()],
                data_converter=data_converter,
            )
        except RuntimeError as e:
            # `Client.connect` surfaces transport-level failures (e.g. a connection reset
            # during the handshake) as RuntimeError. Retry these transient errors with
            # backoff; give up once we exhaust our attempts.
            attempt += 1
            if attempt >= CONNECT_MAX_ATTEMPTS:
                raise

            delay = min(CONNECT_MAX_RETRY_DELAY, CONNECT_INITIAL_RETRY_DELAY * (2 ** (attempt - 1)))
            logger.warning(
                "temporal_client_connect_retry",
                attempt=attempt,
                max_attempts=CONNECT_MAX_ATTEMPTS,
                delay=delay,
                error=str(e),
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
