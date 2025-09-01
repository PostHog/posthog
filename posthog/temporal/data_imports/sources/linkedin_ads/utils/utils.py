"""LinkedIn Ads utility functions for validation, data processing, and circuit breaking."""

import re
import time
import datetime as dt
from collections import defaultdict
from typing import Any

import structlog

from .constants import (
    ACCOUNT_ID_MAX_LENGTH,
    ACCOUNT_ID_MIN_LENGTH,
    CIRCUIT_BREAKER_THRESHOLD,
    CIRCUIT_BREAKER_TIMEOUT,
    LINKEDIN_SPONSORED_URN_PREFIX,
    VALID_PIVOT_VALUES,
)

logger = structlog.get_logger(__name__)

# Simple circuit breaker for tracking failures
_failure_counts: defaultdict[str, int] = defaultdict(int)
_last_failure_time: defaultdict[str, float] = defaultdict(float)


def validate_account_id(account_id: str) -> bool:
    """Validate LinkedIn account ID format.

    LinkedIn account IDs should be numeric strings.

    Args:
        account_id: Account ID to validate

    Returns:
        True if valid, False otherwise
    """
    if not account_id:
        return False

    # Remove any whitespace
    account_id = account_id.strip()

    # Should be numeric and reasonable length (typically 8-12 digits)
    return account_id.isdigit() and ACCOUNT_ID_MIN_LENGTH <= len(account_id) <= ACCOUNT_ID_MAX_LENGTH


def validate_date_format(date_str: str) -> bool:
    """Validate date string is in YYYY-MM-DD format.

    Args:
        date_str: Date string to validate

    Returns:
        True if valid, False otherwise
    """
    if not date_str:
        return False

    # Check exact format with regex first
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False

    try:
        dt.datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_pivot_value(pivot: str) -> bool:
    """Validate LinkedIn ads analytics pivot value.

    Args:
        pivot: Pivot value to validate

    Returns:
        True if valid, False otherwise
    """
    return pivot in VALID_PIVOT_VALUES


def extract_linkedin_id_from_urn(urn: str) -> str:
    """Extract the ID from a LinkedIn URN.

    Args:
        urn: LinkedIn URN like "urn:li:sponsoredCampaign:185129613"

    Returns:
        The extracted ID like "185129613"
    """
    if not urn:
        return urn

    # Split by ':' and take the last part which is the ID
    parts = urn.split(":")
    if len(parts) >= 4 and parts[0] == "urn" and parts[1] == "li" and parts[2].startswith("sponsored"):
        return parts[3]

    # If not a recognized LinkedIn URN format, return as-is
    return urn


# Circuit breaker functions
def check_circuit_breaker(account_id: str) -> bool:
    """Check if circuit breaker is open for an account.

    Args:
        account_id: LinkedIn account ID

    Returns:
        True if circuit is open (should fail fast), False if OK to proceed
    """
    current_time = time.time()

    # Reset failure count if timeout has passed
    if current_time - _last_failure_time[account_id] > CIRCUIT_BREAKER_TIMEOUT:
        _failure_counts[account_id] = 0

    return _failure_counts[account_id] >= CIRCUIT_BREAKER_THRESHOLD


def record_failure(account_id: str) -> None:
    """Record a failure for circuit breaker tracking.

    Args:
        account_id: LinkedIn account ID
    """
    _failure_counts[account_id] += 1
    _last_failure_time[account_id] = time.time()


def record_success(account_id: str) -> None:
    """Record a success, resetting failure count.

    Args:
        account_id: LinkedIn account ID
    """
    _failure_counts[account_id] = 0


# Data transformation utilities
def flatten_date_range(item: dict[str, Any], flattened_item: dict[str, Any]) -> None:
    """Flatten dateRange structure for analytics data.

    Args:
        item: Original item with dateRange structure
        flattened_item: Target flattened item to modify
    """
    if "dateRange" not in item:
        return

    if "start" in item["dateRange"]:
        start = item["dateRange"]["start"]
        flattened_item["date_range_start"] = dt.date(start["year"], start["month"], start["day"])
    if "end" in item["dateRange"]:
        end = item["dateRange"]["end"]
        flattened_item["date_range_end"] = dt.date(end["year"], end["month"], end["day"])


def flatten_pivot_values(item: dict[str, Any], flattened_item: dict[str, Any], resource_name: str) -> None:
    """Transform pivotValues from array to specific pivot columns.

    Args:
        item: Original item with pivotValues structure
        flattened_item: Target flattened item to modify
        resource_name: Name of the resource for logging
    """
    if "pivotValues" not in item or not isinstance(item["pivotValues"], list):
        return

    # Extract IDs and create specific columns based on pivot type
    for pivot_value in item["pivotValues"]:
        if isinstance(pivot_value, str) and pivot_value.startswith(LINKEDIN_SPONSORED_URN_PREFIX):
            # Remove the LinkedIn URN prefix to get the type and ID part
            # "urn:li:sponsoredCampaign:12345678" -> "Campaign:12345678"
            cleaned = pivot_value.replace(LINKEDIN_SPONSORED_URN_PREFIX, "")

            if ":" in cleaned:
                pivot_type, pivot_id_str = cleaned.split(":", 1)  # will be ["Campaign", "12345678"]

                # Convert ID to integer (LinkedIn IDs are always integers)
                try:
                    pivot_id: int | str = int(pivot_id_str)
                except ValueError:
                    logger.warning(
                        "Failed to convert pivot ID to int",
                        pivot_id=pivot_id_str,
                        pivot_type=pivot_type,
                        resource_name=resource_name,
                    )
                    pivot_id = pivot_id_str  # Keep as string if conversion fails

                # Convert pivot type to column name from valid pivot values
                if pivot_type == "Campaign":
                    flattened_item["campaign_id"] = pivot_id
                elif pivot_type == "CampaignGroup":
                    flattened_item["campaign_group_id"] = pivot_id
                elif pivot_type == "Creative":
                    flattened_item["creative_id"] = pivot_id
                elif pivot_type == "Account":
                    flattened_item["account_id"] = pivot_id
                else:
                    # For any other pivot types, use a generic pattern, should never happen
                    column_name = pivot_type.lower() + "_id"
                    flattened_item[column_name] = pivot_id


def flatten_cost_in_usd(item: dict[str, Any], flattened_item: dict[str, Any], resource_name: str) -> None:
    """Convert cost_in_usd from String to Float.

    Args:
        item: Original item with costInUsd field
        flattened_item: Target flattened item to modify
        resource_name: Name of the resource for logging
    """
    if "costInUsd" not in item:
        return

    try:
        flattened_item["cost_in_usd"] = float(item["costInUsd"]) if item["costInUsd"] is not None else None
    except (ValueError, TypeError):
        logger.warning(
            "Failed to convert costInUsd to float", cost_in_usd=item["costInUsd"], resource_name=resource_name
        )
        flattened_item["cost_in_usd"] = None
    # Remove the original camelCase field since we've converted it
    flattened_item.pop("costInUsd", None)


def flatten_change_audit_stamps(item: dict[str, Any], flattened_item: dict[str, Any]) -> None:
    """Flatten changeAuditStamps structure for campaigns/campaign groups.

    Args:
        item: Original item with changeAuditStamps structure
        flattened_item: Target flattened item to modify
    """
    if "changeAuditStamps" not in item:
        return

    if "lastModified" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["lastModified"]:
        flattened_item["last_modified_time"] = item["changeAuditStamps"]["lastModified"]["time"]
    if "created" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["created"]:
        flattened_item["created_time"] = item["changeAuditStamps"]["created"]["time"]


def flatten_data_item(item: dict[str, Any], resource_name: str) -> dict[str, Any]:
    """Flatten a single data item from LinkedIn API response.

    Args:
        item: Original item from API response
        resource_name: Name of the resource for logging

    Returns:
        Flattened item with normalized field names
    """
    flattened_item = item.copy()

    # Apply all flattening functions
    flatten_date_range(item, flattened_item)
    flatten_pivot_values(item, flattened_item, resource_name)
    flatten_cost_in_usd(item, flattened_item, resource_name)
    flatten_change_audit_stamps(item, flattened_item)

    return flattened_item


def determine_primary_keys(resource_name: str, flattened_data: list[dict[str, Any]]) -> list[str] | None:
    """Determine primary keys based on resource type and available data.

    Args:
        resource_name: Name of the resource
        flattened_data: List of flattened data items

    Returns:
        List of primary key field names, or None if no suitable keys found
    """
    from .schemas import LinkedinAdsResource

    if resource_name in [LinkedinAdsResource.CampaignStats, LinkedinAdsResource.CampaignGroupStats]:
        # Analytics data uses combination of fields for uniqueness
        if flattened_data and "pivotValues" in flattened_data[0] and "date_range_start" in flattened_data[0]:
            return ["pivotValues", "date_range_start"]
        elif flattened_data and "date_range_start" in flattened_data[0]:
            return ["date_range_start"]
        else:
            logger.warning("No suitable primary keys found for analytics data", resource_name=resource_name)
            return None
    else:
        # Entity data uses ID field
        if flattened_data and "id" in flattened_data[0]:
            return ["id"]
        else:
            logger.warning("No ID field found for entity data", resource_name=resource_name)
            return None
