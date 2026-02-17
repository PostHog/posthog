from typing import Any

import requests
from requests import Session
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.buildbetter.queries import QUERIES, VIEWER_QUERY
from posthog.temporal.data_imports.sources.buildbetter.settings import (
    BUILDBETTER_API_URL,
    BUILDBETTER_DEFAULT_PAGE_SIZE,
    BUILDBETTER_ENDPOINTS,
)


class BuildBetterRetryableError(Exception):
    pass


def _make_paginated_request(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    incremental_field: str | None = None,
    incremental_field_last_value: str | None = None,
):
    endpoint_config = BUILDBETTER_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown BuildBetter endpoint: {endpoint_name}")

    query = QUERIES.get(endpoint_name)
    if not query:
        raise ValueError(f"No GraphQL query for endpoint: {endpoint_name}")

    graphql_query_name = endpoint_config.graphql_query_name or endpoint_name

    sess = Session()
    sess.headers.update(
        {
            "X-Buildbetter-API-Key": api_key,
            "Content-Type": "application/json",
        }
    )

    @retry(
        retry=retry_if_exception_type(BuildBetterRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(variables: dict[str, Any]) -> dict:
        response = sess.post(BUILDBETTER_API_URL, json={"query": query, "variables": variables}, timeout=60)

        if response.status_code >= 500:
            raise BuildBetterRetryableError(f"BuildBetter: server error {response.status_code}")

        if response.status_code == 429:
            raise BuildBetterRetryableError("BuildBetter: rate limited")

        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(
                    f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {response.text})"
                )
            raise Exception(f"Unexpected BuildBetter response: {response.text}")

        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            joined = "; ".join(error_messages)
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {joined})")
            raise Exception(f"BuildBetter GraphQL error: {joined}")

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {payload})")

        if "data" not in payload:
            raise Exception(f"Unexpected BuildBetter response format. Keys: {list(payload.keys())}")

        return payload

    variables: dict[str, Any] = {
        "limit": BUILDBETTER_DEFAULT_PAGE_SIZE,
        "offset": 0,
    }

    if incremental_field and incremental_field_last_value:
        variables["where"] = {incremental_field: {"_gt": incremental_field_last_value}}

    try:
        while True:
            logger.debug(f"Querying BuildBetter endpoint {endpoint_name} with variables: {variables}")
            payload = execute(variables)

            data = payload["data"][graphql_query_name]
            if not data:
                break

            yield data

            if len(data) < BUILDBETTER_DEFAULT_PAGE_SIZE:
                break

            variables["offset"] = variables["offset"] + len(data)
    finally:
        sess.close()


def buildbetter_source(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = BUILDBETTER_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown BuildBetter endpoint: {endpoint_name}")

    def get_rows():
        incremental_field = None
        incremental_field_last_value = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            incremental_field = endpoint_config.incremental_filter_field
            incremental_field_last_value = str(db_incremental_field_last_value)
            logger.debug(
                f"BuildBetter: incremental sync for {endpoint_name} on {incremental_field} since {incremental_field_last_value}"
            )

        yield from _make_paginated_request(
            api_key=api_key,
            endpoint_name=endpoint_name,
            logger=logger,
            incremental_field=incremental_field,
            incremental_field_last_value=incremental_field_last_value,
        )

    return SourceResponse(
        items=get_rows,
        primary_keys=[endpoint_config.primary_key],
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        response = requests.post(
            BUILDBETTER_API_URL,
            headers={
                "X-Buildbetter-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json={"query": VIEWER_QUERY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            return False, f"BuildBetter API error: {data['errors']}"
        if "data" in data and data["data"].get("interview") is not None:
            return True, None
        return False, "Could not verify BuildBetter credentials"
    except Exception as e:
        return False, str(e)
