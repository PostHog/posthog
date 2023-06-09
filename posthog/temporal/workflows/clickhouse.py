from aiochclient import ChClient
from aiohttp import ClientSession, TCPConnector
from django.conf import settings
from contextlib import asynccontextmanager
import ssl


@asynccontextmanager
async def get_client():
    ssl_context = ssl.create_default_context(capath=settings.CLICKHOUSE_CA)
    ssl_context.check_hostname = True if settings.CLICKHOUSE_VERIFY else False
    ssl_context.verify_mode = ssl.CERT_REQUIRED if settings.CLICKHOUSE_VERIFY else ssl.CERT_NONE
    with TCPConnector(ssl_context=ssl_context) as connector:
        async with ClientSession(connector=connector) as session:
            client = ChClient(
                session,
                url=settings.CLICKHOUSE_HTTP_URL,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE,
            )
            yield client
            await client.close()
