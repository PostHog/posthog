from typing import Any

import requests
from requests import Session
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.linear.queries import QUERIES, VIEWER_QUERY
from posthog.temporal.data_imports.sources.linear.settings import (
    LINEAR_API_URL,
    LINEAR_DEFAULT_PAGE_SIZE,
    LINEAR_ENDPOINTS,
)


class LinearRetryableError(Exception):
    pass


def _make_paginated_request(
    access_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    updated_at_gte: str | None = None,
):
    endpoint_config = LINEAR_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Linear endpoint: {endpoint_name}")

    query = QUERIES.get(endpoint_name)
    if not query:
        raise ValueError(f"No GraphQL query for endpoint: {endpoint_name}")

    graphql_query_name = endpoint_config.graphql_query_name or endpoint_name

    sess = Session()
    sess.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
    )

    @retry(
        retry=retry_if_exception_type(LinearRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(variables: dict[str, Any]) -> dict:
        response = sess.post(LINEAR_API_URL, json={"query": query, "variables": variables})

        if response.status_code == 429:
            raise LinearRetryableError("Linear: rate limit exceeded")
        if response.status_code >= 500:
            raise LinearRetryableError(f"Linear: server error {response.status_code}")

        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise Exception(f"{response.status_code} Client Error: {response.reason} (Linear API: {body})")
        payload = response.json()

        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            joined = "; ".join(error_messages)
            if "ratelimit" in joined.lower() or "rate limit" in joined.lower():
                raise LinearRetryableError(f"Linear: rate limited - {joined}")
            raise Exception(f"Linear GraphQL error: {joined}")

        if "data" not in payload:
            raise Exception(f"Unexpected Linear response format. Keys: {list(payload.keys())}")

        return payload

    variables: dict[str, Any] = {"pageSize": LINEAR_DEFAULT_PAGE_SIZE}

    if updated_at_gte:
        variables["filter"] = {"updatedAt": {"gt": updated_at_gte}}

    try:
        has_next_page = True
        while has_next_page:
            logger.debug(f"Querying Linear endpoint {endpoint_name} with variables: {variables}")
            payload = execute(variables)

            data = payload["data"][graphql_query_name]["nodes"]
            yield data

            page_info = payload["data"][graphql_query_name]["pageInfo"]
            has_next_page = page_info["hasNextPage"]
            if has_next_page:
                variables["cursor"] = page_info["endCursor"]
    finally:
        sess.close()


def linear_source(
    access_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = LINEAR_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Linear endpoint: {endpoint_name}")

    def get_rows():
        updated_at_gte = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            updated_at_gte = str(db_incremental_field_last_value)
            logger.debug(f"Linear: incremental sync for {endpoint_name} since {updated_at_gte}")

        yield from _make_paginated_request(
            access_token=access_token,
            endpoint_name=endpoint_name,
            logger=logger,
            updated_at_gte=updated_at_gte,
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


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    try:
        response = requests.post(
            LINEAR_API_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"query": VIEWER_QUERY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            return False, f"Linear API error: {data['errors']}"
        if "data" in data and data["data"].get("viewer"):
            return True, None
        return False, "Could not verify Linear credentials"
    except Exception as e:
        return False, str(e)
