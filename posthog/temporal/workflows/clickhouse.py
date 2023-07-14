import datetime as dt
import json
import math
import tempfile
import typing
import uuid
from contextlib import asynccontextmanager

import aiohttp
import pyarrow as pa
from django.conf import settings


def encode_query_data(data):
    match data:
        case None:
            return b"NULL"

        case uuid.UUID():
            return str(data).encode("utf-8")

        case int():
            return b"%d" % data

        case dt.datetime():
            timezone_arg = ""
            if data.tzinfo:
                timezone_arg = f", '{data:%Z}'"

            if data.microsecond == 0:
                return f"toDateTime('{data:%Y-%m-%d %H:%M:%S.%f}'{timezone_arg})".encode("utf-8")
            return f"toDateTime64('{data:%Y-%m-%d %H:%M:%S.%f}', {int(math.log10(data.microsecond))}{timezone_arg})".encode(
                "utf-8"
            )

        case list():
            encoded_data = [encode_query_data(value) for value in data]
            result = b"[" + b",".join(encoded_data) + b"]"
            return result

        case tuple():
            encoded_data = [encode_query_data(value) for value in data]
            result = b"(" + b",".join(encoded_data) + b")"
            return result

        case dict():
            return json.dumps(data).encode("utf-8")

        case _:
            str_data = str(data)
            str_data.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{str_data}'".encode("utf-8")


class ClickHouseError(Exception):
    def __init__(self, query, error_message):
        self.query = query
        super().__init__(error_message)


class ClickHouseClient:
    def __init__(
        self,
        session: aiohttp.ClientSession = None,
        url="http://localhost:8123",
        user="default",
        password="",
        database="default",
        **kwargs,
    ):
        self.session = session
        if not self.session:
            self.session = aiohttp.ClientSession()

        self.url = url
        self.headers = {}
        self.params = {}

        if user:
            self.headers["X-ClickHouse-User"] = user
        if password:
            self.headers["X-ClickHouse-Key"] = password
        if database:
            self.params["database"] = database

        self.params.update(kwargs)

    @classmethod
    def from_posthog_settings(cls, session, settings, **kwargs):
        return cls(
            session=session,
            url=settings.CLICKHOUSE_URL,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE,
            **kwargs,
        )

    async def is_alive(self) -> bool:
        try:
            await self.session.get(
                url=self.url, params={**self.params, "query": "SELECT 1"}, headers=self.headers, raise_for_status=True
            )
        except aiohttp.ClientResponseError:
            return False
        return True

    def prepare_query(self, query, query_parameters):
        if query_parameters:
            format_parameters = {k: encode_query_data(v).decode("utf-8") for k, v in query_parameters.items()}
        else:
            format_parameters = {}
        query = query.format(**format_parameters)
        return query

    def prepare_request_data(self, data):
        if len(data) > 0:
            request_data = b",".join(encode_query_data(value) for value in data)
        else:
            request_data = None
        return request_data

    async def check_response(self, response, query) -> None:
        if response.status != 200:
            error_message = await response.text()
            raise ClickHouseError(query, error_message)

    @asynccontextmanager
    async def post_query(self, query, *data, query_parameters, query_id):
        params = {**self.params}
        if query_id is not None:
            params["query_id"] = query_id

        query = self.prepare_query(query, query_parameters)
        request_data = self.prepare_request_data(data)

        if request_data:
            params["query"] = query
        else:
            request_data = query.encode("utf-8")

        async with self.session.post(url=self.url, params=params, headers=self.headers, data=request_data) as response:
            await self.check_response(response, query)
            yield response

    async def execute_query(self, query, *data, query_parameters=None, query_id: str | None = None) -> None:
        async with self.post_query(query, *data, query_parameters=query_parameters, query_id=query_id):
            return None

    async def read_query(self, query, *data, query_parameters=None, query_id: str | None = None) -> bytes:
        async with self.post_query(query, *data, query_parameters=query_parameters, query_id=query_id) as response:
            return await response.content.read()

    async def stream_query_as_jsonl(
        self, query, *data, query_parameters=None, query_id: str | None = None, line_separator=b"\n"
    ) -> typing.AsyncGenerator[dict[typing.Any, typing.Any], None]:
        buffer = b""
        async with self.post_query(query, *data, query_parameters=query_parameters, query_id=query_id) as response:
            async for chunk in response.content.iter_any():
                lines = chunk.split(line_separator)

                yield json.loads(buffer + lines[0])

                buffer = lines.pop(-1)

                for line in lines[1:]:
                    yield json.loads(line)

    async def stream_query_as_arrow(
        self,
        query,
        *data,
        query_parameters=None,
        query_id: str | None = None,
    ) -> typing.AsyncGenerator[dict[typing.Any, typing.Any], None]:
        with tempfile.SpooledTemporaryFile() as temp_file:
            async with self.post_query(query, *data, query_parameters=query_parameters, query_id=query_id) as response:
                async for chunk in response.content.iter_any():
                    temp_file.write(chunk)

            temp_file.seek(0)
            with pa.ipc.open_stream(temp_file) as reader:
                for batch in reader:
                    yield batch

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, tb):
        await self.session.close()


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
    timeout = aiohttp.ClientTimeout(total=None, connect=None, sock_connect=None, sock_read=None)
    with aiohttp.TCPConnector(verify_ssl=False) as connector:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with ClickHouseClient(
                session,
                url=settings.CLICKHOUSE_OFFLINE_HTTP_URL,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE,
                # TODO: make this a setting.
                max_execution_time=0,
            ) as client:
                yield client
