import os
from typing import Any, Optional

import requests
from requests import Session
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.shopify.utils import ShopifyGraphQLObject, safe_unwrap, unwrap

from .constants import (
    SHOPIFY_ACCESS_TOKEN_CHECK,
    SHOPIFY_API_URL,
    SHOPIFY_API_VERSION,
    SHOPIFY_DEFAULT_PAGE_SIZE,
    SHOPIFY_RESOURCES,
)


class ShopifyPermissionError(Exception):
    """Exception raised when Shopify access token lacks permissions for specific resources."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Shopify access token lacks permissions for: {', '.join(missing_permissions.keys())}"
        if os.getenv("DEBUG") == "1":
            message = f"Shopify access token lacks permissions for: {missing_permissions}"
        super().__init__(message)


class ShopifyRateLimitError(Exception):
    """Exception raised when Shopify API rate limit is exceeded."""

    pass


def _is_rate_limited(payload: Any) -> bool:
    """Check if the response indicates a rate limit has been hit."""
    errors, ok = safe_unwrap(payload, path="errors")
    if ok and isinstance(errors, list):
        for error in errors:
            if "throttled" in str(error).lower():
                return True
    currently_available, ok = safe_unwrap(payload, path="extensions.cost.throttleStatus.currentlyAvailable")
    if ok and isinstance(currently_available, int | float):
        # this check is a little liberal. if we find that we are getting rate limited
        # too often might be worth it to check against the requestedCost instead
        return currently_available <= 0
    return False


def _make_paginated_shopify_request(
    url: str, sess: Session, graphql_object: ShopifyGraphQLObject, logger: FilteringBoundLogger
):
    @retry(
        retry=retry_if_exception_type(ShopifyRateLimitError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(vars: dict[str, Any]):
        logger.debug(f"Shopify: reading from resource {graphql_object.name}")
        response = sess.post(url, json={"query": graphql_object.query, "variables": vars})
        response.raise_for_status()
        payload = response.json()
        if _is_rate_limited(payload):
            raise ShopifyRateLimitError("Shopify rate limit exceeded...")
        if "data" in payload:
            return payload
        elif "errors" in payload:
            raise Exception(f"Shopify GraphQL error: {payload['errors']}")
        else:
            raise Exception(f"Unexpected graphql response format in Shopify rows read. Keys: {list(payload.keys())}")

    vars = {"pageSize": SHOPIFY_DEFAULT_PAGE_SIZE}
    has_next_page = True
    while has_next_page:
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
    resource_name: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    api_url = SHOPIFY_API_URL.format(shopify_store_id, SHOPIFY_API_VERSION)

    def get_rows():
        sess = requests.Session()
        sess.headers.update({"X-Shopify-Access-Token": shopify_access_token, "Content-Type": "application/json"})
        resource = SHOPIFY_RESOURCES.get(resource_name)
        if not resource:
            raise Exception(f"Shopify resource does not exist: {resource_name}")
        yield from _make_paginated_shopify_request(api_url, sess, resource, logger)

    return SourceResponse(
        items=get_rows(),
        primary_keys=["id"],
        name=resource_name,
        # column_hints=column_hints,
        # Shopify data is returned in descending timestamp order
        sort_mode="desc",
        # partition_count=1,  # this enables partitioning
        # partition_size=1,  # this enables partitioning
        # partition_mode="datetime",
        # partition_format="month",
        # partition_keys=[incremental_field_name],
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
    for resource_name, resource in SHOPIFY_RESOURCES.items():
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
