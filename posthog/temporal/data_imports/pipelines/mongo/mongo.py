from __future__ import annotations

import collections
from collections.abc import Iterator
from typing import Any

import pyarrow as pa
from bson import ObjectId
from dlt.common.normalizers.naming.snake_case import NamingConvention
from pymongo import MongoClient
from pymongo.collection import Collection

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.source.sql import Column


@config.config
class MongoSourceConfig(config.Config):
    connection_string: str


def _process_nested_value(value: Any) -> Any:
    """Process a nested value, converting ObjectIds to strings."""
    if isinstance(value, ObjectId):
        return str(value)
    elif isinstance(value, dict):
        return _process_nested_object(value)
    elif isinstance(value, list):
        return [_process_nested_value(item) for item in value]
    else:
        return value


def _process_nested_object(obj: dict) -> dict:
    """Process a nested object, converting ObjectIds to strings recursively."""
    processed = {}
    for key, value in obj.items():
        processed[key] = _process_nested_value(value)
    return processed


def _create_mongo_client(connection_string: str, connection_params: dict[str, Any]) -> MongoClient:
    """Create a MongoDB client with the given parameters."""
    # For SRV connections, use the full connection string
    if connection_params["is_srv"]:
        return MongoClient(connection_string, serverSelectionTimeoutMS=5000)

    # For regular connections
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

    return MongoClient(**connection_kwargs)


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

    client = _create_mongo_client(config.connection_string, connection_params)

    if not connection_params["database"]:
        raise ValueError("Database name is required in connection string")

    db = client[connection_params["database"]]
    schema_list = collections.defaultdict(list)

    # Get collection names
    collection_names = db.list_collection_names()

    for collection_name in collection_names:
        # All collections have the same schema: a single 'data' column containing the document
        schema_list[collection_name] = [("data", "object")]

    client.close()
    return schema_list


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


def mongo_source(
    connection_string: str,
    collection_names: list[str],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    collection_name = collection_names[0]
    if not collection_name:
        raise ValueError("Collection name is missing")

    connection_params = _parse_connection_string(connection_string)

    if not connection_params["database"]:
        raise ValueError("Database name is required in connection string")

    # Create MongoDB client
    client = _create_mongo_client(connection_string, connection_params)

    db = client[connection_params["database"]]
    collection = db[collection_name]

    # Get collection metadata
    primary_keys = _get_primary_keys(collection, collection_name)
    rows_to_sync = _get_rows_to_sync(collection, {}, logger)

    client.close()

    def get_rows() -> Iterator[dict[str, Any]]:
        # New connection for data reading
        read_client = _create_mongo_client(connection_string, connection_params)

        read_db = read_client[connection_params["database"]]
        read_collection = read_db[collection_name]

        # TODO: update to pymongoarrow when pyarrow major version is bumped
        try:
            cursor = read_collection.find({})

            for doc in cursor:
                # Convert ObjectId to string and handle nested objects
                processed_doc = {}

                # Process the document to handle ObjectIds and nested structures
                for key, value in doc.items():
                    if isinstance(value, ObjectId):
                        processed_doc[key] = str(value)
                    elif isinstance(value, dict):
                        # Keep nested objects as they are, but convert ObjectIds within them
                        processed_doc[key] = _process_nested_object(value)
                    elif isinstance(value, list):
                        processed_doc[key] = [_process_nested_value(item) for item in value]
                    else:
                        processed_doc[key] = value

                # Wrap the entire document in a 'data' field. Mongo schemas are not stable so we put everything in an object
                yield {"_id": str(doc["_id"]), "data": processed_doc}

        finally:
            read_client.close()

    name = NamingConvention().normalize_identifier(collection_name)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=primary_keys,
        rows_to_sync=rows_to_sync,
    )
