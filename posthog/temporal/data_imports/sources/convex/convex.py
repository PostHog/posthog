import logging
from typing import Any, Iterator

import requests

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.schema import SourceSchema


def _make_request(
    deployment_url: str,
    access_key: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to the Convex API."""
    url = f"{deployment_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Convex {access_key}",
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def validate_convex_credentials(deployment_url: str, access_key: str) -> bool:
    """
    Validate Convex credentials by attempting to fetch schemas.
    """
    try:
        _make_request(deployment_url, access_key, "api/json_schemas", {"deltaSchema": "true", "format": "json"})
        return True
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return False
        raise
    except Exception:
        return False


def get_convex_schemas(deployment_url: str, access_key: str) -> list[SourceSchema]:
    """
    Get list of available tables from Convex deployment.
    """
    try:
        response = _make_request(
            deployment_url, access_key, "api/json_schemas", {"deltaSchema": "true", "format": "json"}
        )

        schemas = []
        # The response contains table names as keys
        for table_name in response.keys():
            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=True,
                    supports_append=True,
                    incremental_fields=["_ts"],  # _ts is the nanosecond timestamp field
                )
            )

        return schemas
    except Exception as e:
        raise Exception(f"Failed to fetch Convex schemas: {str(e)}")


def _fetch_snapshot_page(
    deployment_url: str,
    access_key: str,
    table_name: str,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Fetch a single page from the snapshot export API.
    """
    params: dict[str, Any] = {
        "tableName": table_name,
        "format": "json",
    }

    if cursor:
        params["cursor"] = cursor

    return _make_request(deployment_url, access_key, "api/list_snapshot", params)


def _iter_convex_records(
    deployment_url: str,
    access_key: str,
    table_name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: int | None,
    logger: logging.Logger,
) -> Iterator[list[dict[str, Any]]]:
    """
    Iterate over records from a Convex table, yielding batches of records.
    """
    cursor = None
    has_more = True
    records_fetched = 0

    while has_more:
        try:
            response = _fetch_snapshot_page(deployment_url, access_key, table_name, cursor)

            values = response.get("values", [])
            cursor = response.get("cursor")
            has_more = response.get("hasMore", False)

            if not values:
                break

            # Filter records based on incremental field if needed
            if should_use_incremental_field and db_incremental_field_last_value is not None:
                # _ts is in nanoseconds, filter records newer than the last value
                filtered_values = [
                    record for record in values
                    if record.get("_ts", 0) > db_incremental_field_last_value
                ]

                if filtered_values:
                    records_fetched += len(filtered_values)
                    logger.info(f"Fetched {len(filtered_values)} new records (total: {records_fetched})")
                    yield filtered_values
            else:
                records_fetched += len(values)
                logger.info(f"Fetched {len(values)} records (total: {records_fetched})")
                yield values

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error while fetching Convex data: {e}")
            raise
        except Exception as e:
            logger.error(f"Error while fetching Convex data: {e}")
            raise

    logger.info(f"Completed fetching {records_fetched} total records from table '{table_name}'")


def convex_source(
    deployment_url: str,
    access_key: str,
    table_name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: int | None,
    logger: logging.Logger,
) -> SourceResponse:
    """
    Create a SourceResponse for syncing a Convex table.
    """
    logger.info(f"Starting Convex source for table '{table_name}'")
    logger.info(f"Incremental sync: {should_use_incremental_field}, Last value: {db_incremental_field_last_value}")

    items = _iter_convex_records(
        deployment_url=deployment_url,
        access_key=access_key,
        table_name=table_name,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        logger=logger,
    )

    return SourceResponse(
        items=items,
        primary_keys=["_id"],
        incremental_field="_ts",
        partition_keys=["_creationTime"],
        partition_mode="datetime",
        partition_format="milliseconds",
    )
