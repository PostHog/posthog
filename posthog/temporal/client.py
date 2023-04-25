from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client, TLSConfig


async def connect(host, port, namespace, server_root_ca_cert=None, client_cert=None, client_key=None):
    tls: TLSConfig | bool = False
    if server_root_ca_cert and client_cert and client_key:
        tls = TLSConfig(
            server_root_ca_cert=server_root_ca_cert,
            client_cert=client_cert,
            client_private_key=client_key,
        )
    client = await Client.connect(
        f"{host}:{port}",
        namespace=namespace,
        tls=tls,
    )
    return client


@async_to_sync
async def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    client = await connect(
        settings.TEMPORAL_SCHEDULER_HOST, settings.TEMPORAL_SCHEDULER_PORT, settings.TEMPORAL_NAMESPACE
    )
    return client
