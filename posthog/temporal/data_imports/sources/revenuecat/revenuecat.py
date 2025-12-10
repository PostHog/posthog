import dataclasses
from collections.abc import Iterator

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.revenuecat.settings import (
    DEFAULT_LIMIT,
    REVENUECAT_API_BASE_URL,
    TIMESTAMP_FIELDS,
)


class RevenueCatRetryableError(Exception):
    """Exception raised when RevenueCat API returns a retryable error (e.g. rate limit, 5xx)."""

    pass


@dataclasses.dataclass
class RevenueCatResource:
    path: str


@dataclasses.dataclass
class RevenueCatNestedResource:
    path: str
    parent_path: str
    parent_id_field: str
    nested_parent_param: str


def _convert_ms_to_seconds(item: dict) -> dict:
    for field in TIMESTAMP_FIELDS:
        if field in item and isinstance(item[field], int):
            item[field] = item[field] // 1000
    return item


@retry(
    retry=retry_if_exception_type(RevenueCatRetryableError),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    url: str,
    headers: dict[str, str],
    params: dict[str, str | int],
    logger: FilteringBoundLogger,
) -> tuple[list[dict], str | None]:
    """
    Fetch a single page from RevenueCat API with retry logic.
    Retries on rate limits (429), conflicts (423), and server errors (5xx).
    """
    logger.debug(f"RevenueCat: fetching from {url} with params {params}")

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 423:
        logger.warning(f"RevenueCat: request conflict (423), will retry...")
        raise RevenueCatRetryableError(f"Request conflict: {response.status_code} - {response.text}")

    if response.status_code == 429:
        logger.warning(f"RevenueCat: rate limited (429), will retry...")
        raise RevenueCatRetryableError(f"Rate limited: {response.status_code} - {response.text}")

    if response.status_code >= 500:
        logger.warning(f"RevenueCat: server error ({response.status_code}), will retry...")
        raise RevenueCatRetryableError(f"Server error: {response.status_code} - {response.text}")

    response.raise_for_status()

    data = response.json()
    return data.get("items", []), data.get("next_page")


def _paginate(
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    starting_after: str | None = None,
) -> Iterator[dict]:
    params: dict[str, str | int] = {"limit": DEFAULT_LIMIT}

    if starting_after:
        params["starting_after"] = starting_after
        logger.debug(f"RevenueCat: using incremental sync, starting_after={starting_after}")

    while True:
        items, next_page = _fetch_page(url, headers, params, logger)

        yield from items

        if not next_page:
            break

        url = next_page
        params = {}


def get_rows(
    api_key: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: str | None = None,
) -> Iterator[dict]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "PostHog-DataPipelines",
    }

    resources: dict[str, RevenueCatResource | RevenueCatNestedResource] = {
        "Apps": RevenueCatResource(path=f"/projects/{project_id}/apps"),
        "CustomerActiveEntitlements": RevenueCatNestedResource(
            path=f"/projects/{project_id}/customers/{{customer_id}}/active_entitlements",
            parent_path=f"/projects/{project_id}/customers",
            parent_id_field="id",
            nested_parent_param="customer_id",
        ),
        "CustomerAliases": RevenueCatNestedResource(
            path=f"/projects/{project_id}/customers/{{customer_id}}/aliases",
            parent_path=f"/projects/{project_id}/customers",
            parent_id_field="id",
            nested_parent_param="customer_id",
        ),
        "CustomerPurchases": RevenueCatNestedResource(
            path=f"/projects/{project_id}/customers/{{customer_id}}/purchases",
            parent_path=f"/projects/{project_id}/customers",
            parent_id_field="id",
            nested_parent_param="customer_id",
        ),
        "CustomerSubscriptions": RevenueCatNestedResource(
            path=f"/projects/{project_id}/customers/{{customer_id}}/subscriptions",
            parent_path=f"/projects/{project_id}/customers",
            parent_id_field="id",
            nested_parent_param="customer_id",
        ),
        "Customers": RevenueCatResource(path=f"/projects/{project_id}/customers"),
        "EntitlementProducts": RevenueCatNestedResource(
            path=f"/projects/{project_id}/entitlements/{{entitlement_id}}/products",
            parent_path=f"/projects/{project_id}/entitlements",
            parent_id_field="id",
            nested_parent_param="entitlement_id",
        ),
        "Entitlements": RevenueCatResource(path=f"/projects/{project_id}/entitlements"),
        "OfferingPackages": RevenueCatNestedResource(
            path=f"/projects/{project_id}/offerings/{{offering_id}}/packages",
            parent_path=f"/projects/{project_id}/offerings",
            parent_id_field="id",
            nested_parent_param="offering_id",
        ),
        "Offerings": RevenueCatResource(path=f"/projects/{project_id}/offerings"),
        "Products": RevenueCatResource(path=f"/projects/{project_id}/products"),
    }

    resource = resources.get(endpoint)
    if not resource:
        raise ValueError(f"Unknown RevenueCat endpoint: {endpoint}")

    if isinstance(resource, RevenueCatNestedResource):
        logger.debug(f"RevenueCat: iterating nested resource {endpoint} (full refresh)")

        for parent in _paginate(f"{REVENUECAT_API_BASE_URL}{resource.parent_path}", headers, logger):
            parent_id = parent[resource.parent_id_field]
            child_url = f"{REVENUECAT_API_BASE_URL}{resource.path.format(**{resource.nested_parent_param: parent_id})}"

            for child in _paginate(child_url, headers, logger):
                item = {
                    **child,
                    resource.nested_parent_param: parent_id,
                }
                yield _convert_ms_to_seconds(item)
    else:
        starting_after = None
        if should_use_incremental_field and db_incremental_field_last_value:
            starting_after = db_incremental_field_last_value
            logger.debug(f"RevenueCat: incremental sync for {endpoint}, starting_after={starting_after}")
        else:
            logger.debug(f"RevenueCat: full refresh for {endpoint}")

        for item in _paginate(
            f"{REVENUECAT_API_BASE_URL}{resource.path}",
            headers,
            logger,
            starting_after=starting_after,
        ):
            if endpoint == "Customers":
                item = {
                    **item,
                    "created_at": item.get("first_seen_at"),
                }  # Customers is the only endpoint without a created_at field, adding it for partitioning

            yield _convert_ms_to_seconds(item)


def validate_revenuecat_credentials(api_key: str, project_id: str) -> bool:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "PostHog-DataPipelines",
    }

    response = requests.get(
        f"{REVENUECAT_API_BASE_URL}/projects/{project_id}/customers",
        headers=headers,
        params={"limit": 1},
    )

    return response.status_code == 200


def revenuecat_source(
    api_key: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: str | None = None,
) -> SourceResponse:
    return SourceResponse(
        items=lambda: get_rows(
            api_key=api_key,
            project_id=project_id,
            endpoint=endpoint,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["id"],
        name=endpoint,
        column_hints=None,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=["created_at"],
    )
