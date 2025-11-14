"""Mailgun API integration for data warehouse imports."""

import dataclasses
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.mailgun.settings import (
    BOUNCES_ENDPOINT,
    COMPLAINTS_ENDPOINT,
    DOMAINS_ENDPOINT,
    EVENTS_ENDPOINT,
    UNSUBSCRIBES_ENDPOINT,
)


@dataclasses.dataclass
class MailgunConfig:
    """Configuration for Mailgun API client."""

    api_key: str
    domain: str
    region: str = "US"  # US or EU


class MailgunAPIError(Exception):
    """Exception raised for Mailgun API errors."""

    pass


def get_base_url(region: str) -> str:
    """Get the base URL for the Mailgun API based on region."""
    if region.upper() == "EU":
        return "https://api.eu.mailgun.net/v3"
    return "https://api.mailgun.net/v3"


def validate_credentials(api_key: str, domain: str, region: str = "US") -> bool:
    """Validate Mailgun API credentials by attempting to fetch domains."""
    base_url = get_base_url(region)
    try:
        response = requests.get(
            f"{base_url}/domains/{domain}",
            auth=("api", api_key),
            timeout=30,
        )
        return response.status_code == 200
    except Exception:
        return False


def fetch_events(
    config: MailgunConfig,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any] = None,
    limit: int = 300,
) -> Iterator[dict[str, Any]]:
    """Fetch events from Mailgun API.

    Events include delivered, opened, clicked, bounced, complained, unsubscribed, etc.
    """
    base_url = get_base_url(config.region)
    url = f"{base_url}/{config.domain}/events"

    params: dict[str, Any] = {"limit": limit}

    # If we have a last value, only fetch events after that timestamp
    if db_incremental_field_last_value:
        # Mailgun uses Unix timestamps for filtering
        if isinstance(db_incremental_field_last_value, (int, float)):
            params["begin"] = db_incremental_field_last_value
        elif isinstance(db_incremental_field_last_value, str):
            # Parse string timestamp to Unix timestamp
            dt = datetime.fromisoformat(db_incremental_field_last_value.replace("Z", "+00:00"))
            params["begin"] = int(dt.timestamp())

    has_more = True
    next_url = None

    while has_more:
        try:
            if next_url:
                response = requests.get(next_url, auth=("api", config.api_key), timeout=60)
            else:
                response = requests.get(url, auth=("api", config.api_key), params=params, timeout=60)

            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            if items:
                yield items

            # Check for pagination
            paging = data.get("paging", {})
            next_url = paging.get("next")
            has_more = bool(next_url) and bool(items)

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Mailgun events: {e}")
            raise MailgunAPIError(f"Failed to fetch events: {e}")


def fetch_domains(
    config: MailgunConfig,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """Fetch domains from Mailgun API."""
    base_url = get_base_url(config.region)
    url = f"{base_url}/domains"

    try:
        response = requests.get(url, auth=("api", config.api_key), params={"limit": 1000}, timeout=30)
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        if items:
            yield items

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Mailgun domains: {e}")
        raise MailgunAPIError(f"Failed to fetch domains: {e}")


def fetch_suppressions(
    config: MailgunConfig,
    endpoint_type: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any] = None,
    limit: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Fetch suppression lists (bounces, complaints, unsubscribes) from Mailgun API."""
    base_url = get_base_url(config.region)
    url = f"{base_url}/{config.domain}/{endpoint_type}"

    params: dict[str, Any] = {"limit": limit}

    skip = 0
    has_more = True

    while has_more:
        try:
            current_params = {**params, "skip": skip}
            response = requests.get(url, auth=("api", config.api_key), params=current_params, timeout=30)
            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])

            # Filter by incremental field if provided
            if db_incremental_field_last_value and items:
                filtered_items = []
                for item in items:
                    created_at = item.get("created_at")
                    if created_at:
                        # Parse the created_at timestamp
                        if isinstance(created_at, str):
                            item_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        else:
                            item_dt = datetime.fromtimestamp(created_at, tz=timezone.utc)

                        # Parse the last value
                        if isinstance(db_incremental_field_last_value, str):
                            last_dt = datetime.fromisoformat(db_incremental_field_last_value.replace("Z", "+00:00"))
                        else:
                            last_dt = datetime.fromtimestamp(db_incremental_field_last_value, tz=timezone.utc)

                        if item_dt > last_dt:
                            filtered_items.append(item)
                items = filtered_items

            if items:
                yield items

            # Mailgun uses skip-based pagination for suppressions
            paging = data.get("paging", {})
            total = paging.get("total", 0)
            skip += limit
            has_more = skip < total and bool(items)

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Mailgun {endpoint_type}: {e}")
            raise MailgunAPIError(f"Failed to fetch {endpoint_type}: {e}")


def mailgun_source(
    api_key: str,
    domain: str,
    region: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Main source function for Mailgun data imports."""
    config = MailgunConfig(api_key=api_key, domain=domain, region=region)

    def items_generator() -> Iterator[list[dict[str, Any]]]:
        if endpoint == EVENTS_ENDPOINT:
            yield from fetch_events(
                config=config,
                logger=logger,
                db_incremental_field_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
            )
        elif endpoint == DOMAINS_ENDPOINT:
            yield from fetch_domains(config=config, logger=logger)
        elif endpoint in (BOUNCES_ENDPOINT, COMPLAINTS_ENDPOINT, UNSUBSCRIBES_ENDPOINT):
            yield from fetch_suppressions(
                config=config,
                endpoint_type=endpoint,
                logger=logger,
                db_incremental_field_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
            )
        else:
            logger.error(f"Unknown endpoint: {endpoint}")
            raise ValueError(f"Unknown endpoint: {endpoint}")

    # Determine partition configuration
    partition_keys = None
    partition_mode = None
    partition_format = None

    if endpoint == EVENTS_ENDPOINT:
        # Events have a timestamp field, use datetime partitioning
        partition_keys = ["timestamp"]
        partition_mode = "datetime"
        partition_format = "%Y-%m"
    elif endpoint in (BOUNCES_ENDPOINT, COMPLAINTS_ENDPOINT, UNSUBSCRIBES_ENDPOINT):
        # Suppressions have created_at field
        partition_keys = ["created_at"]
        partition_mode = "datetime"
        partition_format = "%Y-%m"

    return SourceResponse(
        items=items_generator(),
        primary_keys=["id"] if endpoint == EVENTS_ENDPOINT else ["address"],
        sort_mode="ascending",
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_format=partition_format,
    )
