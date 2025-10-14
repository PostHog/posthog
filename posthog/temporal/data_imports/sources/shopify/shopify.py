import os
from collections.abc import Iterable
from typing import Any, Optional

import requests
from gql import (
    Client as GQLClient,
    gql,
)
from gql.transport.aiohttp import AIOHTTPTransport
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.graphql_source.constants import (
    GRAPHQL_DATA_KEY,
    GRAPHQL_DEFAULT_PAGE_SIZE,
    GRAPHQL_ERRORS_KEY,
    GRAPHQL_EXTENSIONS_KEY,
)

from .constants import SHOPIFY_ACCESS_TOKEN_CHECK, SHOPIFY_API_URL, SHOPIFY_API_VERSION, SHOPIFY_RESOURCES


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


def _is_rate_limited(response: dict[str, Any]) -> bool:
    """Check if the response indicates a rate limit has been hit."""
    if GRAPHQL_ERRORS_KEY in response:
        errors = response[GRAPHQL_ERRORS_KEY]
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict) and "THROTTLED" in str(error).upper():
                    return True

    if GRAPHQL_EXTENSIONS_KEY in response:
        extensions = response[GRAPHQL_EXTENSIONS_KEY]
        if isinstance(extensions, dict) and "cost" in extensions:
            cost = extensions["cost"]
            if isinstance(cost, dict) and "throttleStatus" in cost:
                throttle = cost["throttleStatus"]
                if isinstance(throttle, dict):
                    currently_available = throttle.get("currentlyAvailable", float("inf"))
                    return currently_available <= 0

    return False


# FIX: implement this
def _validate_shopify_store_url(raw_url: str) -> str | None:
    """Returns a validated shopify store url if possible, None if invalid."""
    return f"{raw_url}/admin/api/2025-10/graphql.json"


def shopify_source(
    shopify_store_url: str,
    shopify_access_token: str,
    resource_name: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    validated_url = _validate_shopify_store_url(shopify_store_url)
    if not validated_url:
        raise Exception(
            "The Shopify store URL provided doesn't seem to match common Shopify URL patterns. Make sure you are providing a valid Shopify URL that looks like https://mystore.myshopify.com OR https://shop.mystore.com."
        )

    def get_rows():
        transport = AIOHTTPTransport(
            url=validated_url,
            headers={
                "X-Shopify-Access-Token": shopify_access_token,
                "Content-Type": "application/json",
            },
        )
        default_vars = {"pageSize": GRAPHQL_DEFAULT_PAGE_SIZE}
        client = GQLClient(transport=transport)
        resource = SHOPIFY_RESOURCES.get(resource_name)
        if not resource:
            raise Exception(f"Shopify resource does not exist: {resource_name}")

        @retry(
            retry=retry_if_exception_type(ShopifyRateLimitError),
            stop=stop_after_attempt(5),
            wait=wait_exponential_jitter(initial=1, max=30),
            reraise=True,
        )
        def execute():
            logger.debug(f"Shopify: reading from resource {resource_name}")
            response = client.execute(gql(resource.query), variable_values=default_vars)

            if _is_rate_limited(response):
                logger.warning(f"Shopify: rate limit hit for resource {resource_name}, retrying...")
                raise ShopifyRateLimitError(f"Rate limit exceeded for resource {resource_name}")

            if GRAPHQL_DATA_KEY in response:
                return response[GRAPHQL_DATA_KEY]
            elif GRAPHQL_ERRORS_KEY in response:
                raise Exception(f"Shopify GraphQL error: {response[GRAPHQL_ERRORS_KEY]}")
            else:
                raise Exception(
                    f"Unexpected graphql response format in Shopify rows read. Keys: {list(response.keys())}"
                )

        data = execute()
        if isinstance(data, Iterable):
            yield from data
        else:
            yield data

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


def validate_credentials(shopify_store_url: str, shopify_access_token: str) -> bool:
    """
    Validates Shopify API credentials and checks permissions for all required resources.
    This function will:
    - Return True if the access token is valid and has all required permissions
    - Raise ShopifyPermissionError if the access token is valid but lacks permissions for specific resources
    - Raise Exception if the access token is invalid or there's any other error
    """
    api_url = SHOPIFY_API_URL.format(store_url=shopify_store_url, api_version=SHOPIFY_API_VERSION)
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
        if GRAPHQL_ERRORS_KEY in data:
            raise Exception(f"Failed to verify your Shopify credentials: {data[GRAPHQL_ERRORS_KEY]}")
    except Exception as e:
        raise Exception(f"Failed to verify your Shopify credentials: {e}")

    # test fine grained permissions
    missing_permissions: dict[str, str] = {}
    for resource_name, resource in SHOPIFY_RESOURCES.items():
        try:
            res = sess.post(api_url, json={"query": resource.permissions_query})
            res.raise_for_status()
            data = res.json()
            if GRAPHQL_ERRORS_KEY in data:
                missing_permissions[resource_name] = (
                    f"Failed to verify Shopify access privileges for resource {resource_name}: {data[GRAPHQL_ERRORS_KEY]}"
                )
        except Exception as e:
            missing_permissions[resource_name] = str(e)
    if missing_permissions:
        raise ShopifyPermissionError(missing_permissions)
    return True
