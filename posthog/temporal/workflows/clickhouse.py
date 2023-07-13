import enum
import typing
from contextlib import asynccontextmanager

import aiochclient
import sqlparse
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from django.conf import settings


class ClickHouseFormat(str, enum.Enum):
    CSV = "CSV"
    JSONEachRow = "JSONEachRow"
    Parquet = "Parquet"
    TSVWithNamesAndTypes = "TSVWithNamesAndTypes"


class RawFabric:
    """A record fabric that simply returns the given bytes."""

    def new(self, row: bytes) -> bytes:
        return row


class ToFileFabric:
    """A record fabric that writes files to given file object."""

    def __init__(self, file_obj: typing.BinaryIO):
        self.file_obj = file_obj

    def new(self, row: bytes) -> int:
        return self.file_obj.write(row)


class FormattableChClient(aiochclient.ChClient):
    """Extend ChClient to support multiple formats."""

    @staticmethod
    def _parse_squery(query):
        statement = sqlparse.parse(query)[0]
        statement_type = statement.get_type()
        if statement_type in ("SELECT", "SHOW", "DESCRIBE", "EXISTS"):
            need_fetch = True
        else:
            need_fetch = False

        fmt = statement.token_matching((lambda tk: tk.match(sqlparse.tokens.Keyword, "FORMAT"),), 0)
        fmt_token = None
        if fmt:
            idx, _ = fmt
            fmt_token = statement.token_next(idx)

        return need_fetch, fmt_token, statement_type

    async def _execute(
        self,
        query,
        *args,
        format_type: ClickHouseFormat = ClickHouseFormat.JSONEachRow,
        json: bool = False,
        record_fabric=None,
        query_params,
        query_id,
        decode,
    ):
        query_params = self._prepare_query_params(query_params)
        if query_params:
            query = query.format(**query_params)
        need_fetch, fmt_token, _ = self._parse_squery(query)

        if not need_fetch:
            async for record in super()._execute(
                query,
                *args,
                json=format_type == ClickHouseFormat.JSONEachRow,
                query_params=query_params,
                query_id=query_id,
                decode=decode,
            ):
                yield record
                return

        if json:
            format_type = ClickHouseFormat.JSONEachRow

        if decode:
            format_type = ClickHouseFormat.TSVWithNamesAndTypes
            record_fabric = aiochclient.records.RecordsFabric

        if not fmt_token and format_type:
            query += f" FORMAT {format_type}"

        params = {**self.params}
        data = query.encode()

        if query_id is not None:
            params["query_id"] = query_id

        response = self._http_client.post_return_lines(url=self.url, params=params, headers=self.headers, data=data)

        if json:
            record_fabric = aiochclient.records.FromJsonFabric(loads=self._json.loads)
        if decode:
            record_fabric = aiochclient.records.RecordsFabric(
                names=await response.__anext__(),
                tps=await response.__anext__(),
                convert=decode,
            )

        async for line in response:
            yield record_fabric.new(line)


class ClickHouseActivities:
    """Base class for Temporal activities that require a ClickHouse client."""

    def __init__(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        max_execution_time: int = 0,
    ):
        self.url = url or settings.CLICKHOUSE_OFFLINE_HTTP_URL
        self.user = user or settings.CLICKHOUSE_USER
        self.password = password or settings.CLICKHOUSE_PASSWORD
        self.database = database or settings.CLICKHOUSE_DATABASE
        self.max_execution_time = max_execution_time

    @asynccontextmanager
    async def get_client(self):
        """Returns a ClickHouse client based on the aiochclient library. This is an
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
        connector = TCPConnector(ssl=False)
        timeout = ClientTimeout()
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with FormattableChClient(
                session,
                url=self.url,
                user=self.user,
                password=self.password,
                database=self.database,
                max_execution_time=self.max_execution_time,
            ) as client:
                yield client
