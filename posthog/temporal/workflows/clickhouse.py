from contextlib import asynccontextmanager

from aiochclient import ChClient
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from django.conf import settings


@asynccontextmanager
async def get_client():
    """
    Returns a ClickHouse client based on the aiochclient library. This is an
    async context manager.

    Usage:

        async with get_client() as client:
            await client.execute("SELECT 1")

    Note that this is not a connection pool, so you should not use this for
    queries that are run frequently.

    Note that we setup the SSL context here, allowing for custom CA certs to be
    used. I couldn't see a simply way to do this with `aiochclient` so we
    explicitly use `aiohttp` to create the client session with an ssl_context
    and pass that to `aiochclient`.
    """
    # Set up SSL context, roughly based on how `clickhouse_driver` does it.
    # TODO: figure out why this is not working when we set CERT_REQUIRED. We
    # include a custom CA cert in the Docker image and set the path to it in
    # the settings, but I can't get this to work as expected.
    #
    # ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    # ssl_context.verify_mode = ssl.CERT_REQUIRED if settings.CLICKHOUSE_VERIFY else ssl.CERT_NONE
    # if ssl_context.verify_mode is ssl.CERT_REQUIRED:
    #    if settings.CLICKHOUSE_CA:
    #        ssl_context.load_verify_locations(settings.CLICKHOUSE_CA)
    #    elif ssl_context.verify_mode is ssl.CERT_REQUIRED:
    #        ssl_context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    timeout = ClientTimeout(total=None, connect=None, sock_connect=None, sock_read=None)
    with TCPConnector(verify_ssl=False) as connector:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            client = ChClient(
                session,
                url=settings.CLICKHOUSE_OFFLINE_HTTP_URL,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE,
            )
            yield client
            await client.close()
