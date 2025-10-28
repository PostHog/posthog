import os
import json
from typing import Any, Optional

import requests
from requests import Session
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.shopify.constants import ID
from posthog.temporal.data_imports.sources.shopify.settings import ENDPOINT_CONFIGS
from posthog.temporal.data_imports.sources.shopify.utils import ShopifyGraphQLObject, safe_unwrap, unwrap

from .constants import (
    SHOPIFY_ACCESS_TOKEN_CHECK,
    SHOPIFY_API_URL,
    SHOPIFY_API_VERSION,
    SHOPIFY_DEFAULT_PAGE_SIZE,
    SHOPIFY_GRAPHQL_OBJECTS,
)


class ShopifyPermissionError(Exception):
    """Exception raised when Shopify access token lacks permissions for specific resources."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Shopify access token lacks permissions for: {', '.join(missing_permissions.keys())}"
        if os.getenv("DEBUG") == "1":
            message = f"Shopify access token lacks permissions for: {missing_permissions}"
        super().__init__(message)


class ShopifyRetryableError(Exception):
    """Exception raised when Shopify issues a retryable error (e.g. rate limit, 5xx)."""

    pass


def _get_retryable_error(payload: Any) -> ShopifyRetryableError | None:
    """Check if the response indicates a retryable error in the payload (e.g. rate limit, 5xx)"""
    errors, ok = safe_unwrap(payload, path="errors")
    if ok:
        serialized_errors = json.dumps(errors).lower()
        if "throttled" in serialized_errors:
            return ShopifyRetryableError("Shopify: rate limit exceeded...")
        if "internal_server_error" in serialized_errors:
            return ShopifyRetryableError(f"Shopify: internal errors in payload {serialized_errors}")
    currently_available, ok = safe_unwrap(payload, path="extensions.cost.throttleStatus.currentlyAvailable")
    if ok and isinstance(currently_available, int | float):
        # this check is a little liberal. if we find that we are getting rate limited
        # too often might be worth it to check against the requestedCost instead
        if currently_available <= 0:
            return ShopifyRetryableError("Shopify: rate limit exceeded...")
    return None


def _make_paginated_shopify_request(
    url: str,
    sess: Session,
    graphql_object: ShopifyGraphQLObject,
    logger: FilteringBoundLogger,
    query: str | None = None,
):
    @retry(
        retry=retry_if_exception_type(ShopifyRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(vars: dict[str, Any]):
        response = sess.post(url, json={"query": graphql_object.query, "variables": vars})
        if response.status_code >= 500:
            raise ShopifyRetryableError(
                f"Shopify: internal error from request {response.status_code} {response.reason}"
            )
        else:
            response.raise_for_status()
        payload = response.json()
        retryable_error = _get_retryable_error(payload)
        if retryable_error:
            raise retryable_error
        if "data" in payload:
            return payload
        elif "errors" in payload:
            raise Exception(f"Shopify GraphQL error: {payload['errors']}")
        else:
            raise Exception(f"Unexpected graphql response format in Shopify rows read. Keys: {list(payload.keys())}")

    vars: dict[str, Any] = {"pageSize": SHOPIFY_DEFAULT_PAGE_SIZE}
    if query:
        vars.update({"query": query})
    has_next_page = True
    while has_next_page:
        logger.debug(f"Querying shopify endpoint {graphql_object.name} with vars: {vars}")
        payload = execute(vars)
        data_iter = unwrap(payload, path=f"data.{graphql_object.name}.nodes")
        yield data_iter
        page_info = unwrap(payload, path=f"data.{graphql_object.name}.pageInfo")
        has_next_page = page_info.get("hasNextPage", False)
        if has_next_page:
            # this is intentionally an unsafe lookup so errors surface if expectations aren't met
            vars.update({"cursor": page_info["endCursor"]})


def shopify_source(
    shopify_store_id: str,
    shopify_access_token: str,
    graphql_object_name: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    api_url = SHOPIFY_API_URL.format(shopify_store_id, SHOPIFY_API_VERSION)

    def get_rows():
        sess = requests.Session()
        sess.headers.update({"X-Shopify-Access-Token": shopify_access_token, "Content-Type": "application/json"})
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS.get(graphql_object_name)
        if not graphql_object:
            raise Exception(f"Shopify object does not exist: {graphql_object_name}")

        logger.debug(f"Shopify: reading from resource {graphql_object_name}")

        if not should_use_incremental_field or (
            db_incremental_field_last_value is None and db_incremental_field_earliest_value is None
        ):
            logger.debug(f"Shopify: iterating all objects from source for {graphql_object_name}")
            yield from _make_paginated_shopify_request(api_url, sess, graphql_object, logger)
            return

        endpoint_config = ENDPOINT_CONFIGS.get(graphql_object_name)
        # query_filer is ignored if the key isn't present in the endpoint's available query filters
        query_filter = endpoint_config.query_filter if endpoint_config else "created_at"

        # check for any objects less than the minimum object we already have
        if db_incremental_field_earliest_value is not None:
            logger.debug(
                f"Shopify: iterating earliest objects from source: {query_filter} < {db_incremental_field_earliest_value}"
            )
            query = f"{query_filter}:<'{db_incremental_field_earliest_value}'"
            yield from _make_paginated_shopify_request(api_url, sess, graphql_object, logger, query=query)

        # check for any objects more than the maximum object we already have
        if db_incremental_field_last_value is not None:
            logger.debug(
                f"Shopify: iterating latest objects from source: {query_filter} > {db_incremental_field_last_value}"
            )
            query = f"{query_filter}:>'{db_incremental_field_last_value}'"
            yield from _make_paginated_shopify_request(api_url, sess, graphql_object, logger, query=query)

    endpoint_config = ENDPOINT_CONFIGS.get(graphql_object_name)
    if not endpoint_config:
        raise ValueError(f"Endpoint {graphql_object_name} has no config in shopify/settings.py")
    return SourceResponse(
        items=get_rows(),
        primary_keys=[ID],
        name=graphql_object_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(shopify_store_id: str, shopify_access_token: str) -> bool:
    """
    Validates Shopify API credentials and checks permissions for all required resources.
    This function will:
    - Return True if the access token is valid and has all required permissions
    - Raise ShopifyPermissionError if the access token is valid but lacks permissions for specific resources
    - Raise Exception if the access token is invalid or there's any other error
    """
    api_url = SHOPIFY_API_URL.format(shopify_store_id, SHOPIFY_API_VERSION)
    sess = requests.Session()
    sess.headers.update(
        {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": shopify_access_token,
        }
    )

    # tests the validity of the access token (valid tokens can always access the shop resource)
    try:
        res = sess.post(api_url, json={"query": SHOPIFY_ACCESS_TOKEN_CHECK})
        res.raise_for_status()
        data = res.json()
        if "errors" in data:
            raise Exception(f"Failed to verify your Shopify credentials: {data['errors']}")
    except Exception as e:
        raise Exception(f"Failed to verify your Shopify credentials: {e}")

    # test fine grained permissions
    missing_permissions: dict[str, str] = {}
    for resource_name, resource in SHOPIFY_GRAPHQL_OBJECTS.items():
        try:
            res = sess.post(api_url, json={"query": resource.permissions_query})
            res.raise_for_status()
            data = res.json()
            if "errors" in data:
                missing_permissions[resource_name] = (
                    f"Failed to verify Shopify access privileges for resource {resource_name}: {data['errors']}"
                )
        except Exception as e:
            missing_permissions[resource_name] = str(e)
    if missing_permissions:
        raise ShopifyPermissionError(missing_permissions)
    return True
