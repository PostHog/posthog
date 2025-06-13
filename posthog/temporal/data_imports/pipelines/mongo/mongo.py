from __future__ import annotations

import collections
import math
from collections.abc import Iterator
from typing import Any, Optional

import pyarrow as pa
from bson import ObjectId
from dlt.common.normalizers.naming.snake_case import NamingConvention
from pymongo import MongoClient
from pymongo.collection import Collection

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    table_from_iterator,
)
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.source.sql import Column, Table
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.warehouse.models.ssh_tunnel import SSHTunnel, SSHTunnelConfig
from posthog.warehouse.types import IncrementalFieldType, PartitionSettings


@config.config
class MongoSourceConfig(config.Config):
    connection_string: str
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MongoSourceConfig:
        """Create MongoSourceConfig from dictionary, handling SSH tunnel configuration."""
        ssh_tunnel_config = None

        # Handle SSH tunnel configuration from job_inputs format
        if data.get("ssh_tunnel_enabled"):
            ssh_tunnel_config = SSHTunnelConfig(
                enabled=data.get("ssh_tunnel_enabled", False),
                host=data.get("ssh_tunnel_host"),
                port=data.get("ssh_tunnel_port"),
                auth_type=data.get("ssh_tunnel_auth_type"),
                username=data.get("ssh_tunnel_auth_type_username"),
                password=data.get("ssh_tunnel_auth_type_password"),
                passphrase=data.get("ssh_tunnel_auth_type_passphrase"),
                private_key=data.get("ssh_tunnel_auth_type_private_key"),
            )
        # Handle SSH tunnel configuration from nested format
        elif "ssh_tunnel" in data and isinstance(data["ssh_tunnel"], dict):
            ssh_tunnel_data = data["ssh_tunnel"]
            if ssh_tunnel_data.get("enabled"):
                auth_data = ssh_tunnel_data.get("auth", {})
                ssh_tunnel_config = SSHTunnelConfig(
                    enabled=ssh_tunnel_data.get("enabled", False),
                    host=ssh_tunnel_data.get("host"),
                    port=ssh_tunnel_data.get("port"),
                    auth_type=auth_data.get("type"),
                    username=auth_data.get("username"),
                    password=auth_data.get("password"),
                    passphrase=auth_data.get("passphrase"),
                    private_key=auth_data.get("private_key"),
                )

        return cls(
            connection_string=data["connection_string"],
            ssh_tunnel=ssh_tunnel_config,
        )


def _parse_connection_string(connection_string: str) -> dict[str, Any]:
    """Parse MongoDB connection string and extract connection parameters."""
    from urllib.parse import urlparse, parse_qs

    # Handle mongodb:// and mongodb+srv:// schemes
    parsed = urlparse(connection_string)

    if parsed.scheme not in ["mongodb", "mongodb+srv"]:
        raise ValueError("Connection string must start with mongodb:// or mongodb+srv://")

    # Extract basic connection info
    host = parsed.hostname or "localhost"
    port = parsed.port or (27017 if parsed.scheme == "mongodb" else None)
    database = parsed.path.lstrip("/") if parsed.path else None
    user = parsed.username
    password = parsed.password

    # Parse query parameters
    query_params = parse_qs(parsed.query)

    # Extract common parameters
    auth_source = query_params.get("authSource", ["admin"])[0]
    tls = query_params.get("tls", ["false"])[0].lower() in ["true", "1"]
    ssl = query_params.get("ssl", ["false"])[0].lower() in ["true", "1"]

    # TLS can be specified as either tls or ssl
    use_tls = tls or ssl

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "auth_source": auth_source,
        "tls": use_tls,
        "connection_string": connection_string,
        "is_srv": parsed.scheme == "mongodb+srv",
    }


def get_schemas(config: MongoSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all collections from MongoDB source database to sync."""

    connection_params = _parse_connection_string(config.connection_string)

    def inner(mongo_host: str, mongo_port: int):
        # For SRV connections, use the full connection string
        if connection_params["is_srv"]:
            client = MongoClient(config.connection_string, serverSelectionTimeoutMS=5000)
        else:
            connection_kwargs = {
                "host": mongo_host,
                "port": mongo_port,
                "serverSelectionTimeoutMS": 5000,
            }

            if connection_params["user"] and connection_params["password"]:
                connection_kwargs.update(
                    {
                        "username": connection_params["user"],
                        "password": connection_params["password"],
                        "authSource": connection_params["auth_source"],
                    }
                )

            if connection_params["tls"]:
                connection_kwargs["tls"] = True

            client = MongoClient(**connection_kwargs)

        if not connection_params["database"]:
            raise ValueError("Database name is required in connection string")

        db = client[connection_params["database"]]

        schema_list = collections.defaultdict(list)

        # Get collection names
        collection_names = db.list_collection_names()

        for collection_name in collection_names:
            collection = db[collection_name]

            # Sample a few documents to infer schema
            sample = list(collection.find().limit(100))

            if sample:
                # Get field types from the sample
                fields = set()
                for doc in sample:
                    fields.update(doc.keys())

                for field in fields:
                    # Infer type from first document that has this field
                    field_type = "string"  # default
                    for doc in sample:
                        if field in doc:
                            value = doc[field]
                            if isinstance(value, bool):
                                field_type = "boolean"
                            elif isinstance(value, int):
                                field_type = "integer"
                            elif isinstance(value, float):
                                field_type = "double"
                            elif isinstance(value, ObjectId):
                                field_type = "string"  # ObjectId as string
                            elif isinstance(value, list):
                                field_type = "array"
                            elif isinstance(value, dict):
                                field_type = "object"
                            break

                    schema_list[collection_name].append((field, field_type))
            else:
                # Empty collection, add _id field as default
                schema_list[collection_name].append(("_id", "string"))

        client.close()
        return schema_list

    if config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

        with ssh_tunnel.get_tunnel(connection_params["host"], connection_params["port"] or 27017) as tunnel:
            if tunnel is None:
                raise ConnectionError("Can't open tunnel to SSH server")

            return inner(tunnel.local_bind_host, tunnel.local_bind_port)

    return inner(connection_params["host"], connection_params["port"] or 27017)


def _build_query(
    collection_name: str,
    is_incremental: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    query = {}

    if not is_incremental:
        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = {incremental_field: {"$gte": db_incremental_field_last_value}}

    return query


def _get_primary_keys(collection: Collection, collection_name: str) -> list[str] | None:
    # MongoDB always has _id as primary key
    return ["_id"]


def _get_rows_to_sync(collection: Collection, query: dict[str, Any], logger: FilteringBoundLogger) -> int:
    try:
        rows_to_sync = collection.count_documents(query)
        logger.debug(f"_get_rows_to_sync: rows_to_sync={rows_to_sync}")
        return rows_to_sync
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)
        return 0


def _get_partition_settings(
    collection: Collection, collection_name: str, partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
) -> PartitionSettings | None:
    """Get partition settings for given MongoDB collection."""
    try:
        # Get collection stats
        stats = collection.database.command("collStats", collection_name)

        collection_size = stats.get("size", 0)  # size in bytes
        row_count = stats.get("count", 0)

        if collection_size == 0 or row_count == 0:
            return None

        # Calculate partition count based on size
        partition_count = max(1, math.ceil(collection_size / partition_size_bytes))

        # Cap at reasonable limit
        partition_count = min(partition_count, 100)

        partition_size = math.ceil(row_count / partition_count)

        return PartitionSettings(
            partition_count=partition_count,
            partition_size=partition_size,
        )
    except Exception:
        return None


class MongoColumn(Column):
    def __init__(
        self,
        name: str,
        data_type: str,
        nullable: bool = True,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        if self.data_type == "boolean":
            arrow_type = pa.bool_()
        elif self.data_type == "integer":
            arrow_type = pa.int64()
        elif self.data_type == "double":
            arrow_type = pa.float64()
        elif self.data_type == "array":
            arrow_type = pa.list_(pa.string())
        elif self.data_type == "object":
            arrow_type = pa.string()  # JSON as string
        else:  # string, ObjectId, etc.
            arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _get_table(collection: Collection, collection_name: str, schema_info: list[tuple[str, str]]) -> Table[MongoColumn]:
    columns = []

    for field_name, field_type in schema_info:
        column = MongoColumn(
            name=field_name,
            data_type=field_type,
            nullable=True,  # MongoDB fields are generally nullable
        )
        columns.append(column)

    return Table(name=collection_name, columns=columns)


def mongo_source(
    connection_string: str,
    collection_names: list[str],
    is_incremental: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    ssh_tunnel: SSHTunnelConfig | None = None,
) -> SourceResponse:
    collection_name = collection_names[0]
    if not collection_name:
        raise ValueError("Collection name is missing")

    connection_params = _parse_connection_string(connection_string)

    if not connection_params["database"]:
        raise ValueError("Database name is required in connection string")

    # Handle SSH tunnel
    if ssh_tunnel and ssh_tunnel.enabled:
        ssh_tunnel_obj = SSHTunnel.from_config(ssh_tunnel)
        with ssh_tunnel_obj.get_tunnel(connection_params["host"], connection_params["port"] or 27017) as tunnel:
            if tunnel is None:
                raise ConnectionError("Can't open tunnel to SSH server")

            # For tunneled connections, modify the connection string to use tunnel endpoints
            if connection_params["is_srv"]:
                # For SRV connections, we can't easily modify the connection string
                # Fall back to manual connection parameters
                connection_kwargs = {
                    "host": tunnel.local_bind_host,
                    "port": tunnel.local_bind_port,
                    "serverSelectionTimeoutMS": 5000,
                }

                if connection_params["user"] and connection_params["password"]:
                    connection_kwargs.update(
                        {
                            "username": connection_params["user"],
                            "password": connection_params["password"],
                            "authSource": connection_params["auth_source"],
                        }
                    )

                if connection_params["tls"]:
                    connection_kwargs["tls"] = True

                client = MongoClient(**connection_kwargs)
            else:
                # For regular connections, modify the connection string
                from urllib.parse import urlparse, urlunparse

                parsed = urlparse(connection_string)
                # Replace host and port in the connection string
                new_netloc = (
                    f"{parsed.username}:{parsed.password}@{tunnel.local_bind_host}:{tunnel.local_bind_port}"
                    if parsed.username
                    else f"{tunnel.local_bind_host}:{tunnel.local_bind_port}"
                )
                tunneled_connection_string = urlunparse(parsed._replace(netloc=new_netloc))
                client = MongoClient(tunneled_connection_string, serverSelectionTimeoutMS=5000)
    else:
        # No SSH tunnel - use original connection logic
        if connection_params["is_srv"]:
            client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
        else:
            connection_kwargs = {
                "host": connection_params["host"],
                "port": connection_params["port"] or 27017,
                "serverSelectionTimeoutMS": 5000,
            }

            if connection_params["user"] and connection_params["password"]:
                connection_kwargs.update(
                    {
                        "username": connection_params["user"],
                        "password": connection_params["password"],
                        "authSource": connection_params["auth_source"],
                    }
                )

            if connection_params["tls"]:
                connection_kwargs["tls"] = True

            client = MongoClient(**connection_kwargs)

    db = client[connection_params["database"]]
    collection = db[collection_name]

    # Build query
    query = _build_query(
        collection_name,
        is_incremental,
        incremental_field,
        incremental_field_type,
        db_incremental_field_last_value,
    )

    # Get collection metadata
    primary_keys = _get_primary_keys(collection, collection_name)
    rows_to_sync = _get_rows_to_sync(collection, query, logger)
    partition_settings = _get_partition_settings(collection, collection_name) if is_incremental else None

    # Get schema info
    schema_info = []
    sample = list(collection.find(query).limit(100))

    if sample:
        fields = set()
        for doc in sample:
            fields.update(doc.keys())

        for field in fields:
            field_type = "string"  # default
            for doc in sample:
                if field in doc:
                    value = doc[field]
                    if isinstance(value, bool):
                        field_type = "boolean"
                    elif isinstance(value, int):
                        field_type = "integer"
                    elif isinstance(value, float):
                        field_type = "double"
                    elif isinstance(value, ObjectId):
                        field_type = "string"
                    elif isinstance(value, list):
                        field_type = "array"
                    elif isinstance(value, dict):
                        field_type = "object"
                    break

            schema_info.append((field, field_type))
    else:
        schema_info.append(("_id", "string"))

    table = _get_table(collection, collection_name, schema_info)

    client.close()

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()

        # New connection for data reading - reuse the same connection logic
        if ssh_tunnel and ssh_tunnel.enabled:
            ssh_tunnel_obj = SSHTunnel.from_config(ssh_tunnel)
            with ssh_tunnel_obj.get_tunnel(connection_params["host"], connection_params["port"] or 27017) as tunnel:
                if tunnel is None:
                    raise ConnectionError("Can't open tunnel to SSH server")

                if connection_params["is_srv"]:
                    connection_kwargs = {
                        "host": tunnel.local_bind_host,
                        "port": tunnel.local_bind_port,
                        "serverSelectionTimeoutMS": 5000,
                    }

                    if connection_params["user"] and connection_params["password"]:
                        connection_kwargs.update(
                            {
                                "username": connection_params["user"],
                                "password": connection_params["password"],
                                "authSource": connection_params["auth_source"],
                            }
                        )

                    if connection_params["tls"]:
                        connection_kwargs["tls"] = True

                    read_client = MongoClient(**connection_kwargs)
                else:
                    from urllib.parse import urlparse, urlunparse

                    parsed = urlparse(connection_string)
                    new_netloc = (
                        f"{parsed.username}:{parsed.password}@{tunnel.local_bind_host}:{tunnel.local_bind_port}"
                        if parsed.username
                        else f"{tunnel.local_bind_host}:{tunnel.local_bind_port}"
                    )
                    tunneled_connection_string = urlunparse(parsed._replace(netloc=new_netloc))
                    read_client = MongoClient(tunneled_connection_string, serverSelectionTimeoutMS=5000)
        else:
            if connection_params["is_srv"]:
                read_client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            else:
                connection_kwargs = {
                    "host": connection_params["host"],
                    "port": connection_params["port"] or 27017,
                    "serverSelectionTimeoutMS": 5000,
                }

                if connection_params["user"] and connection_params["password"]:
                    connection_kwargs.update(
                        {
                            "username": connection_params["user"],
                            "password": connection_params["password"],
                            "authSource": connection_params["auth_source"],
                        }
                    )

                if connection_params["tls"]:
                    connection_kwargs["tls"] = True

                read_client = MongoClient(**connection_kwargs)

        read_db = read_client[connection_params["database"]]
        read_collection = read_db[collection_name]

        try:
            cursor = read_collection.find(query)

            if is_incremental and incremental_field:
                cursor = cursor.sort(incremental_field, 1)  # ascending order

            batch = []
            for doc in cursor:
                # Convert ObjectId to string and handle nested objects
                processed_doc = {}

                # First, initialize all schema fields with None
                for field_name, _ in schema_info:
                    processed_doc[field_name] = None

                # Then populate with actual document values
                for key, value in doc.items():
                    if isinstance(value, ObjectId):
                        processed_doc[key] = str(value)
                    elif isinstance(value, dict):
                        processed_doc[key] = str(value)  # JSON as string
                    elif isinstance(value, list):
                        processed_doc[key] = [str(item) if isinstance(item, ObjectId) else item for item in value]
                    else:
                        processed_doc[key] = value

                batch.append(processed_doc)

                if len(batch) >= chunk_size:
                    yield table_from_iterator(batch, arrow_schema)
                    batch = []

            # Yield remaining batch
            if batch:
                yield table_from_iterator(batch, arrow_schema)

        finally:
            read_client.close()

    name = NamingConvention().normalize_identifier(collection_name)

    return SourceResponse(
        name=name,
        items=get_rows(DEFAULT_CHUNK_SIZE),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
    )
