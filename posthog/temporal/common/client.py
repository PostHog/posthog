import dataclasses
from typing import Any

import temporalio.converter
from asgiref.sync import async_to_sync
from django.conf import settings as django_settings
from temporalio.client import Client, TLSConfig
from temporalio.runtime import Runtime

from posthog.temporal.common.codec import EncryptionCodec


async def connect(
    host: str,
    port: int | str,
    namespace: str,
    server_root_ca_cert: str | None = None,
    client_cert: str | None = None,
    client_key: str | None = None,
    runtime: Runtime | None = None,
    settings: Any | None = django_settings,
) -> Client:
    tls: TLSConfig | bool = False
    if server_root_ca_cert and client_cert and client_key:
        tls = TLSConfig(
            server_root_ca_cert=bytes(server_root_ca_cert, "utf-8"),
            client_cert=bytes(client_cert, "utf-8"),
            client_private_key=bytes(client_key, "utf-8"),
        )
    client = await Client.connect(
        f"{host}:{port}",
        namespace=namespace,
        tls=tls,
        runtime=runtime,
        data_converter=dataclasses.replace(
            temporalio.converter.default(),
            payload_codec=EncryptionCodec(settings=settings),
        )
        if settings is not None
        else temporalio.converter.default(),
    )
    return client


@async_to_sync
async def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    client = await connect(
        django_settings.TEMPORAL_HOST,
        django_settings.TEMPORAL_PORT,
        django_settings.TEMPORAL_NAMESPACE,
        django_settings.TEMPORAL_CLIENT_ROOT_CA,
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
        django_settings.TEMPORAL_CLIENT_ROOT_CA,
        django_settings.TEMPORAL_CLIENT_CERT,
        django_settings.TEMPORAL_CLIENT_KEY,
    )
    return client
