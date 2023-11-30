import dataclasses

import temporalio.converter
from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client, TLSConfig

from posthog.temporal.common.codec import EncryptionCodec


async def connect(
    host,
    port,
    namespace,
    server_root_ca_cert=None,
    client_cert=None,
    client_key=None,
    runtime=None,
):
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
        ),
    )
    return client


@async_to_sync
async def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )
    return client
