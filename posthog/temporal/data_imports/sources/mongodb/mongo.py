from __future__ import annotations

import math
import contextlib
import collections
from collections.abc import Iterator
from typing import Any, Optional

import certifi
from bson import ObjectId
from dlt.common.normalizers.naming.snake_case import NamingConvention
from pymongo import MongoClient
from pymongo.collection import Collection
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings


def _process_nested_value(value: Any) -> Any:
    """Process a nested value, converting ObjectIds to strings."""
    if isinstance(value, ObjectId):
        return str(value)
    elif isinstance(value, dict):
        return {key: _process_nested_value(val) for key, val in value.items()}
    elif isinstance(value, list):
        return [_process_nested_value(item) for item in value]
    else:
        return value


def get_indexes(connection_string: str, collection_name: str) -> list[str]:
    """Get all indexes for a MongoDB collection."""
    try:
        connection_params = _parse_connection_string(connection_string)
        with mongo_client(connection_string, connection_params) as client:
            db = client[connection_params["database"]]
            collection = db[collection_name]

            index_cursor = collection.list_indexes()
        return [field for index in index_cursor for field in index["key"].keys()]
    except Exception:
        return []


def filter_mongo_incremental_fields(
    columns: list[tuple[str, str]], connection_string: str, collection_name: str
) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    indexed_fields = get_indexes(connection_string, collection_name)

    for column_name, type in columns:
        # Only include fields that have indexes
        if column_name not in indexed_fields:
            continue

        type = type.lower()
        if type == "timestamp":
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "integer":
            results.append((column_name, IncrementalFieldType.Integer))
        elif column_name == "_id" and type == "string":
            results.append((column_name, IncrementalFieldType.ObjectID))

    return results


def _build_query(
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    query: dict[str, Any] = {}

    if not should_use_incremental_field:
        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    if incremental_field_type == IncrementalFieldType.ObjectID:
        query = {incremental_field: {"$gt": ObjectId(str(db_incremental_field_last_value)), "$exists": True}}
    else:
        query = {incremental_field: {"$gt": db_incremental_field_last_value, "$exists": True}}

    return query


@contextlib.contextmanager
def mongo_client(connection_string: str, connection_params: dict[str, Any]) -> Iterator[MongoClient]:
    """Yield a MongoDB client with the given parameters."""
    # For SRV connections, use the full connection string
    if connection_params["is_srv"]:
        client: MongoClient = MongoClient(
            connection_string, serverSelectionTimeoutMS=10000, tls=True, tlsCAFile=certifi.where()
        )
        try:
            yield client
        finally:
            client.close()
        return

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
        connection_kwargs["tlsCAFile"] = certifi.where()

    client = MongoClient(**connection_kwargs)

    try:
        yield client
    finally:
        client.close()


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


def _parse_connection_string(connection_string: str) -> dict[str, Any]:
    """Parse MongoDB connection string and extract connection parameters."""
    from urllib.parse import parse_qs, urlparse

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


def _get_schema_from_query(collection: Collection) -> list[tuple[str, str]]:
    """Infer schema from MongoDB collection using aggregation to get all document keys and types."""
    try:
        # Use aggregation pipeline to get all unique keys and their types
        pipeline: list[dict[str, Any]] = [
            # Convert each document to an array of key-value pairs
            {"$project": {"arrayofkeyvalue": {"$objectToArray": "$$ROOT"}}},
            # Unwind the array to get individual key-value pairs
            {"$unwind": "$arrayofkeyvalue"},
            # Group by key name and collect unique types
            {
                "$group": {
                    "_id": "$arrayofkeyvalue.k",
                    "types": {"$addToSet": {"$type": "$arrayofkeyvalue.v"}},
                }
            },
        ]

        result = list(collection.aggregate(pipeline))

        if not result:
            return [("_id", "string")]

        schema_info = []
        for field_info in result:
            field_name = field_info["_id"]
            types = field_info["types"]

            # Determine the most appropriate type
            # MongoDB $type returns BSON type names, map them to our type system
            field_type = _determine_field_type_from_bson_types(types)
            schema_info.append((field_name, field_type))

        return schema_info

    except Exception:
        # Fallback to basic schema if aggregation fails
        return [("_id", "string")]


def _determine_field_type_from_bson_types(bson_types: list[str]) -> str:
    """Determine field type from BSON types."""
    # If multiple types exist, prioritize based on hierarchy
    type_priority = {
        "objectId": "string",
        "string": "string",
        "int": "integer",
        "long": "integer",
        "double": "double",
        "decimal": "double",
        "bool": "boolean",
        "date": "timestamp",
        "timestamp": "timestamp",
        "object": "object",
        "array": "array",
        "null": "string",
    }

    # Find the highest priority type
    for bson_type in [
        "objectId",
        "timestamp",
        "date",
        "double",
        "decimal",
        "long",
        "int",
        "bool",
        "array",
        "object",
        "string",
    ]:
        if bson_type in bson_types:
            return type_priority.get(bson_type, "string")

    return "string"


def get_schemas(config: MongoDBSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all collections from MongoDB source database to sync."""

    connection_params = _parse_connection_string(config.connection_string)

    with mongo_client(config.connection_string, connection_params) as client:
        if not connection_params["database"]:
            raise ValueError("Database name is required in connection string")

        db = client[connection_params["database"]]
        schema_list = collections.defaultdict(list)

        # Get collection names
        collection_names = db.list_collection_names()

        for collection_name in collection_names:
            collection = db[collection_name]
            # Use aggregation query to get all document keys and types
            schema_info = _get_schema_from_query(collection)
            schema_list[collection_name].extend(schema_info)

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


def mongo_source(
    connection_string: str,
    collection_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    connection_params = _parse_connection_string(connection_string)

    if not connection_params["database"]:
        raise ValueError("Database name is required in connection string")

    # Create MongoDB client
    with mongo_client(connection_string, connection_params) as client:
        db = client[connection_params["database"]]
        collection = db[collection_name]

        query = _build_query(
            should_use_incremental_field,
            incremental_field,
            incremental_field_type,
            db_incremental_field_last_value,
        )

        # Get collection metadata
        primary_keys = _get_primary_keys(collection, collection_name)
        partition_settings = (
            _get_partition_settings(collection, collection_name) if should_use_incremental_field else None
        )
        rows_to_sync = _get_rows_to_sync(collection, query, logger)

    def get_rows() -> Iterator[dict[str, Any]]:
        # New connection for data reading
        with mongo_client(connection_string, connection_params) as read_client:
            read_db = read_client[connection_params["database"]]
            read_collection = read_db[collection_name]

            query = _build_query(
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )

            cursor = read_collection.find(query, batch_size=DEFAULT_CHUNK_SIZE)

            for doc in cursor:
                # Convert ObjectId to string and handle nested objects
                processed_doc = {}

                # Process the document to handle ObjectIds and nested structures
                for key, value in doc.items():
                    if isinstance(value, ObjectId):
                        processed_doc[key] = str(value)
                    elif isinstance(value, dict) or isinstance(value, list):
                        # Keep nested objects as they are, but convert ObjectIds within them
                        processed_doc[key] = _process_nested_value(value)
                    else:
                        processed_doc[key] = value

                result: dict[str, Any] = {
                    "_id": str(doc["_id"]),
                }
                # extract incremental field from the document if it exists
                if incremental_field:
                    incremental_value = processed_doc.get(incremental_field, None)
                    if incremental_value is None:
                        continue
                    result[incremental_field] = incremental_value

                result["data"] = processed_doc

                yield result

    name = NamingConvention().normalize_identifier(collection_name)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
    )
