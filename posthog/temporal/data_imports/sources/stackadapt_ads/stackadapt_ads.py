import re
import json
from typing import Any

import requests
from requests import Session
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.stackadapt_ads.constants import (
    CAMPAIGN_STATS_DAILY,
    STACKADAPT_DEFAULT_PAGE_SIZE,
    STACKADAPT_GRAPHQL_ENDPOINTS,
    STACKADAPT_GRAPHQL_URL,
    StackAdaptGraphQLEndpoint,
)
from posthog.temporal.data_imports.sources.stackadapt_ads.settings import ENDPOINT_CONFIGS


class StackAdaptRetryableError(Exception):
    pass


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _flatten_stats_node(node: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    campaign = node.get("campaign", {}) or {}
    flat["campaign_id"] = campaign.get("id")
    flat["campaign_name"] = campaign.get("name")

    granularity = node.get("granularity", {}) or {}
    flat["date"] = granularity.get("startTime")

    metrics = node.get("metrics", {}) or {}
    for key, value in metrics.items():
        flat[_camel_to_snake(key)] = value

    return flat


def _flatten_entity_node(node: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in node.items():
        snake_key = _camel_to_snake(key)
        if isinstance(value, dict) and "id" in value:
            flat[f"{snake_key}_id"] = value.get("id")
            if "name" in value:
                flat[f"{snake_key}_name"] = value.get("name")
        else:
            flat[snake_key] = value
    return flat


def _make_paginated_request(
    sess: Session,
    endpoint: StackAdaptGraphQLEndpoint,
    logger: FilteringBoundLogger,
    extra_variables: dict[str, Any] | None = None,
):
    @retry(
        retry=retry_if_exception_type(StackAdaptRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(variables: dict[str, Any]):
        response = sess.post(
            STACKADAPT_GRAPHQL_URL,
            json={"query": endpoint.query, "variables": variables},
        )
        if response.status_code == 429:
            raise StackAdaptRetryableError("StackAdapt: rate limit exceeded")
        if response.status_code >= 500:
            raise StackAdaptRetryableError(f"StackAdapt: server error {response.status_code} {response.reason}")
        response.raise_for_status()

        payload = response.json()
        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            serialized = json.dumps(error_messages).lower()
            if "throttled" in serialized or "rate" in serialized:
                raise StackAdaptRetryableError(f"StackAdapt: rate limited: {error_messages}")
            raise Exception(f"StackAdapt GraphQL errors: {error_messages}")

        if "data" not in payload:
            raise Exception(f"StackAdapt: unexpected response format. Keys: {list(payload.keys())}")

        return payload

    variables: dict[str, Any] = {"first": STACKADAPT_DEFAULT_PAGE_SIZE}
    if extra_variables:
        variables.update(extra_variables)

    has_next_page = True
    while has_next_page:
        logger.debug(f"StackAdapt: querying {endpoint.name} with vars: {variables}")
        payload = execute(variables)
        nodes = payload["data"][endpoint.connection_path]["nodes"]
        yield nodes
        page_info = payload["data"][endpoint.connection_path]["pageInfo"]
        has_next_page = page_info.get("hasNextPage", False)
        if has_next_page:
            variables["after"] = page_info["endCursor"]


def stackadapt_ads_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    graphql_endpoint = STACKADAPT_GRAPHQL_ENDPOINTS.get(endpoint)
    if not graphql_endpoint:
        raise ValueError(f"Unknown StackAdapt endpoint: {endpoint}")

    endpoint_config = ENDPOINT_CONFIGS.get(endpoint)
    if not endpoint_config:
        raise ValueError(f"No endpoint config for StackAdapt endpoint: {endpoint}")

    is_stats = endpoint == CAMPAIGN_STATS_DAILY
    flatten_fn = _flatten_stats_node if is_stats else _flatten_entity_node

    def get_rows():
        sess = requests.Session()
        sess.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }
        )

        extra_variables: dict[str, Any] | None = None
        if is_stats:
            if should_use_incremental_field and db_incremental_field_last_value:
                extra_variables = {
                    "startTime": db_incremental_field_last_value,
                    "endTime": "2099-12-31T23:59:59Z",
                }
            else:
                extra_variables = {
                    "startTime": "2020-01-01T00:00:00Z",
                    "endTime": "2099-12-31T23:59:59Z",
                }

        for page in _make_paginated_request(sess, graphql_endpoint, logger, extra_variables):
            yield [flatten_fn(node) for node in page]

    return SourceResponse(
        items=get_rows,
        primary_keys=endpoint_config.primary_keys,
        name=endpoint,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_token: str) -> bool:
    sess = requests.Session()
    sess.headers.update(
        {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
    )
    response = sess.post(
        STACKADAPT_GRAPHQL_URL,
        json={"query": "{ campaigns(first: 1) { nodes { id } } }"},
        timeout=10,
    )
    if response.status_code == 401:
        raise Exception("Invalid StackAdapt API token")
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise Exception(f"StackAdapt credential validation failed: {data['errors']}")
    return True
