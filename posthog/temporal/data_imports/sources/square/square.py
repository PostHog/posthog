from typing import Any, Optional
from datetime import datetime
from structlog.types import FilteringBoundLogger
from square.client import Client as SquareClient
from square.http.auth.o_auth_2 import BearerAuthCredentials

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.square.settings import (
    PAYMENTS,
    CUSTOMERS,
    ORDERS,
    ITEMS,
    CATEGORIES,
    DISCOUNTS,
    TAXES,
    MODIFIER_LISTS,
    REFUNDS,
    LOCATIONS,
    TEAM_MEMBERS,
    SHIFTS,
    INVENTORY,
    INCREMENTAL_FIELDS,
)


class SquarePermissionError(Exception):
    """Raised when the Square access token lacks required permissions."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        super().__init__(f"Missing permissions: {missing_permissions}")


def validate_credentials(access_token: str) -> bool:
    """Validate Square credentials by attempting to list locations."""
    try:
        client = SquareClient(bearer_auth_credentials=BearerAuthCredentials(access_token=access_token))
        result = client.locations.list_locations()

        if result.is_error():
            # Check if the error is due to permissions
            errors = result.errors or []
            permission_errors = {}
            for error in errors:
                if error.get("category") in ["AUTHENTICATION_ERROR", "AUTHORIZATION_ERROR"]:
                    permission_errors[error.get("code", "UNKNOWN")] = error.get("detail", "Unknown error")

            if permission_errors:
                raise SquarePermissionError(permission_errors)
            return False

        return True
    except SquarePermissionError:
        raise
    except Exception:
        return False


def _parse_datetime(dt_str: str) -> datetime:
    """Parse Square's RFC 3339 datetime strings."""
    # Square uses RFC 3339 format
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def _format_datetime(dt: datetime) -> str:
    """Format datetime for Square API (RFC 3339)."""
    return dt.isoformat().replace("+00:00", "Z")


def get_rows(
    access_token: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    """Fetch rows from Square API."""
    client = SquareClient(bearer_auth_credentials=BearerAuthCredentials(access_token=access_token))
    batcher = Batcher(logger=logger)

    # Get the incremental field name for this endpoint
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    # Determine if we should use incremental sync
    use_incremental = (
        should_use_incremental_field
        and incremental_field_name
        and db_incremental_field_last_value is not None
    )

    if endpoint == PAYMENTS:
        # List payments with optional date filtering
        body = {"limit": 100}

        if use_incremental:
            # Square payments API uses begin_time and end_time filters
            body["begin_time"] = db_incremental_field_last_value

        cursor = None
        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.payments.list_payments(**body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            payments = result.body.get("payments", [])
            if not payments:
                break

            for payment in payments:
                batcher.batch(payment)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == CUSTOMERS:
        # List customers
        cursor = None
        body = {"limit": 100}

        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.customers.list_customers(**body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            customers = result.body.get("customers", [])
            if not customers:
                break

            for customer in customers:
                # Filter by incremental field if needed
                if use_incremental and customer.get(incremental_field_name):
                    if customer[incremental_field_name] <= db_incremental_field_last_value:
                        continue

                batcher.batch(customer)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == ORDERS:
        # Search orders
        body = {
            "limit": 100,
            "location_ids": None,  # All locations
        }

        if use_incremental:
            body["query"] = {
                "filter": {
                    "date_time_filter": {
                        "created_at": {
                            "start_at": db_incremental_field_last_value
                        }
                    }
                }
            }

        cursor = None
        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.orders.search_orders(body=body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            orders = result.body.get("orders", [])
            if not orders:
                break

            for order in orders:
                batcher.batch(order)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == REFUNDS:
        # List payment refunds
        body = {"limit": 100}

        if use_incremental:
            body["begin_time"] = db_incremental_field_last_value

        cursor = None
        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.refunds.list_payment_refunds(**body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            refunds = result.body.get("refunds", [])
            if not refunds:
                break

            for refund in refunds:
                batcher.batch(refund)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint in [ITEMS, CATEGORIES, DISCOUNTS, TAXES, MODIFIER_LISTS]:
        # List catalog objects
        types_map = {
            ITEMS: "ITEM",
            CATEGORIES: "CATEGORY",
            DISCOUNTS: "DISCOUNT",
            TAXES: "TAX",
            MODIFIER_LISTS: "MODIFIER_LIST",
        }

        cursor = None
        body = {"types": types_map[endpoint]}

        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.catalog.list_catalog(**body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            objects = result.body.get("objects", [])
            if not objects:
                break

            for obj in objects:
                # Filter by incremental field if needed
                if use_incremental and obj.get(incremental_field_name):
                    if obj[incremental_field_name] <= db_incremental_field_last_value:
                        continue

                batcher.batch(obj)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == LOCATIONS:
        # List locations
        result = client.locations.list_locations()

        if result.is_error():
            logger.error(f"Square API error: {result.errors}")
            return

        locations = result.body.get("locations", [])
        for location in locations:
            batcher.batch(location)

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == TEAM_MEMBERS:
        # List team members
        body = {"limit": 100}
        cursor = None

        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.team.search_team_members(body=body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            team_members = result.body.get("team_members", [])
            if not team_members:
                break

            for member in team_members:
                batcher.batch(member)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == SHIFTS:
        # Search shifts
        body = {"limit": 100}

        if use_incremental:
            body["query"] = {
                "filter": {
                    "start": {
                        "start_at": db_incremental_field_last_value
                    }
                }
            }

        cursor = None
        while True:
            if cursor:
                body["cursor"] = cursor

            result = client.labor.search_shifts(body=body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                break

            shifts = result.body.get("shifts", [])
            if not shifts:
                break

            for shift in shifts:
                batcher.batch(shift)
                if batcher.should_yield():
                    yield batcher.get_table()

            cursor = result.body.get("cursor")
            if not cursor:
                break

        if batcher.has_items():
            yield batcher.get_table()

    elif endpoint == INVENTORY:
        # Batch retrieve inventory counts
        # First, get all catalog items to know what to check
        result = client.catalog.list_catalog(types="ITEM")

        if result.is_error():
            logger.error(f"Square API error: {result.errors}")
            return

        catalog_objects = result.body.get("objects", [])
        catalog_object_ids = [obj["id"] for obj in catalog_objects if "id" in obj]

        # Batch retrieve inventory counts (max 100 at a time)
        for i in range(0, len(catalog_object_ids), 100):
            batch_ids = catalog_object_ids[i:i + 100]
            body = {"catalog_object_ids": batch_ids}

            result = client.inventory.batch_retrieve_inventory_counts(body=body)

            if result.is_error():
                logger.error(f"Square API error: {result.errors}")
                continue

            counts = result.body.get("counts", [])
            for count in counts:
                batcher.batch(count)
                if batcher.should_yield():
                    yield batcher.get_table()

        if batcher.has_items():
            yield batcher.get_table()


def square_source(
    access_token: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Create a SourceResponse for Square data."""

    # Determine partition settings
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field = incremental_field_config[0]["field"] if incremental_field_config else None

    # Use created_at/updated_at for partitioning where available
    partition_keys = [incremental_field] if incremental_field else None
    partition_mode = "datetime" if incremental_field else None

    # Determine primary keys based on endpoint
    primary_keys_map = {
        PAYMENTS: ["id"],
        CUSTOMERS: ["id"],
        ORDERS: ["id"],
        ITEMS: ["id"],
        CATEGORIES: ["id"],
        DISCOUNTS: ["id"],
        TAXES: ["id"],
        MODIFIER_LISTS: ["id"],
        REFUNDS: ["id"],
        LOCATIONS: ["id"],
        TEAM_MEMBERS: ["id"],
        SHIFTS: ["id"],
        INVENTORY: ["catalog_object_id", "location_id", "state"],
    }

    primary_keys = primary_keys_map.get(endpoint, ["id"])

    return SourceResponse(
        items=get_rows(
            access_token=access_token,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
        ),
        primary_keys=primary_keys,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
    )
