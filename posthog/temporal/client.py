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
