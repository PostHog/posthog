from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client, TLSConfig


async def connect(host, port, namespace, server_root_ca_cert=None, client_cert=None, client_key=None):
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
    )
    return client


@async_to_sync
async def sync_connect() -> Client:
    """Synchronous connect to Temporal and return a Client."""
    client = await connect(settings.TEMPORAL_HOST, settings.TEMPORAL_PORT, settings.TEMPORAL_NAMESPACE)
    return client
