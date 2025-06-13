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
    host: str
    database: str
    port: int = config.value(converter=int, default=27017)
    user: str | None = None
    password: str | None = None
    auth_source: str = "admin"
    tls: bool = False
    ssh_tunnel: SSHTunnelConfig | None = None


def get_schemas(config: MongoSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all collections from MongoDB source database to sync."""

    def inner(mongo_host: str, mongo_port: int):
        connection_kwargs = {
            "host": mongo_host,
            "port": mongo_port,
            "serverSelectionTimeoutMS": 5000,
        }

        if config.user and config.password:
            connection_kwargs.update(
                {
                    "username": config.user,
                    "password": config.password,
                    "authSource": config.auth_source,
                }
            )

        if config.tls:
            connection_kwargs["tls"] = True

        client = MongoClient(**connection_kwargs)
        db = client[config.database]

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

        with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
            if tunnel is None:
                raise ConnectionError("Can't open tunnel to SSH server")

            return inner(tunnel.local_bind_host, tunnel.local_bind_port)

    return inner(config.host, config.port)


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
    host: str,
    port: int,
    database: str,
    collection_names: list[str],
    is_incremental: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    user: Optional[str] = None,
    password: Optional[str] = None,
    auth_source: str = "admin",
    tls: bool = False,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    collection_name = collection_names[0]
    if not collection_name:
        raise ValueError("Collection name is missing")

    connection_kwargs = {
        "host": host,
        "port": port,
        "serverSelectionTimeoutMS": 5000,
    }

    if user and password:
        connection_kwargs.update(
            {
                "username": user,
                "password": password,
                "authSource": auth_source,
            }
        )

    if tls:
        connection_kwargs["tls"] = True

    client = MongoClient(**connection_kwargs)
    db = client[database]
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

        # New connection for data reading
        read_client = MongoClient(**connection_kwargs)
        read_db = read_client[database]
        read_collection = read_db[collection_name]

        try:
            cursor = read_collection.find(query)

            if is_incremental and incremental_field:
                cursor = cursor.sort(incremental_field, 1)  # ascending order

            batch = []
            for doc in cursor:
                # Convert ObjectId to string and handle nested objects
                processed_doc = {}
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
