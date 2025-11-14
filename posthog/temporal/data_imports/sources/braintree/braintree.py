from datetime import datetime
from typing import Any

import braintree
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


class BraintreePermissionError(Exception):
    """Exception raised when Braintree credentials lack permissions for specific resources."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Braintree credentials lack permissions for: {', '.join(missing_permissions.keys())}"
        super().__init__(message)


def _get_braintree_gateway(
    merchant_id: str, public_key: str, private_key: str, environment: str
) -> braintree.BraintreeGateway:
    """Create a Braintree gateway instance with the provided credentials."""
    env = braintree.Environment.Production if environment == "production" else braintree.Environment.Sandbox

    return braintree.BraintreeGateway(
        braintree.Configuration(
            environment=env,
            merchant_id=merchant_id,
            public_key=public_key,
            private_key=private_key,
        )
    )


def _serialize_braintree_object(obj: Any) -> dict[str, Any]:
    """Convert a Braintree object to a dictionary, handling nested objects and special types."""
    if obj is None:
        return None

    result = {}

    # Get all attributes from the object
    for attr in dir(obj):
        if attr.startswith("_"):
            continue

        try:
            value = getattr(obj, attr)

            # Skip methods
            if callable(value):
                continue

            # Handle datetime objects
            if isinstance(value, datetime):
                result[attr] = value.isoformat()
            # Handle nested Braintree objects
            elif hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool)):
                result[attr] = _serialize_braintree_object(value)
            # Handle lists of Braintree objects
            elif isinstance(value, list):
                result[attr] = [
                    _serialize_braintree_object(item)
                    if hasattr(item, "__dict__") and not isinstance(item, (str, int, float, bool))
                    else item
                    for item in value
                ]
            else:
                result[attr] = value
        except Exception:
            continue

    return result


def _fetch_transactions(
    gateway: braintree.BraintreeGateway,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    db_incremental_field_earliest_value: Any | None = None,
):
    """Fetch transactions from Braintree using search API."""
    logger.debug("Braintree: fetching transactions")

    search_criteria = []

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            # Fetch transactions created after the last known value
            logger.debug(f"Braintree: fetching transactions created after {db_incremental_field_last_value}")
            search_criteria.append(
                braintree.TransactionSearch.created_at >= datetime.fromisoformat(db_incremental_field_last_value)
            )

        if db_incremental_field_earliest_value:
            # Fetch transactions created before the earliest known value
            logger.debug(f"Braintree: fetching transactions created before {db_incremental_field_earliest_value}")
            search_criteria.append(
                braintree.TransactionSearch.created_at < datetime.fromisoformat(db_incremental_field_earliest_value)
            )

    if search_criteria:
        transactions = gateway.transaction.search(*search_criteria)
    else:
        # Fetch all transactions
        logger.debug("Braintree: fetching all transactions")
        transactions = gateway.transaction.search()

    batch = []
    for transaction in transactions:
        serialized = _serialize_braintree_object(transaction)
        batch.append(serialized)

        if len(batch) >= 100:
            yield batch
            batch = []

    if batch:
        yield batch


def _fetch_customers(
    gateway: braintree.BraintreeGateway,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    db_incremental_field_earliest_value: Any | None = None,
):
    """Fetch customers from Braintree using search API."""
    logger.debug("Braintree: fetching customers")

    search_criteria = []

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            logger.debug(f"Braintree: fetching customers created after {db_incremental_field_last_value}")
            search_criteria.append(
                braintree.CustomerSearch.created_at >= datetime.fromisoformat(db_incremental_field_last_value)
            )

        if db_incremental_field_earliest_value:
            logger.debug(f"Braintree: fetching customers created before {db_incremental_field_earliest_value}")
            search_criteria.append(
                braintree.CustomerSearch.created_at < datetime.fromisoformat(db_incremental_field_earliest_value)
            )

    if search_criteria:
        customers = gateway.customer.search(*search_criteria)
    else:
        logger.debug("Braintree: fetching all customers")
        customers = gateway.customer.search()

    batch = []
    for customer in customers:
        serialized = _serialize_braintree_object(customer)
        batch.append(serialized)

        if len(batch) >= 100:
            yield batch
            batch = []

    if batch:
        yield batch


def _fetch_subscriptions(
    gateway: braintree.BraintreeGateway,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    db_incremental_field_earliest_value: Any | None = None,
):
    """Fetch subscriptions from Braintree using search API."""
    logger.debug("Braintree: fetching subscriptions")

    search_criteria = []

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            logger.debug(f"Braintree: fetching subscriptions created after {db_incremental_field_last_value}")
            search_criteria.append(
                braintree.SubscriptionSearch.created_at >= datetime.fromisoformat(db_incremental_field_last_value)
            )

        if db_incremental_field_earliest_value:
            logger.debug(f"Braintree: fetching subscriptions created before {db_incremental_field_earliest_value}")
            search_criteria.append(
                braintree.SubscriptionSearch.created_at < datetime.fromisoformat(db_incremental_field_earliest_value)
            )

    if search_criteria:
        subscriptions = gateway.subscription.search(*search_criteria)
    else:
        logger.debug("Braintree: fetching all subscriptions")
        subscriptions = gateway.subscription.search()

    batch = []
    for subscription in subscriptions:
        serialized = _serialize_braintree_object(subscription)
        batch.append(serialized)

        if len(batch) >= 100:
            yield batch
            batch = []

    if batch:
        yield batch


def _fetch_disputes(
    gateway: braintree.BraintreeGateway,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    db_incremental_field_earliest_value: Any | None = None,
):
    """Fetch disputes from Braintree using search API."""
    logger.debug("Braintree: fetching disputes")

    search_criteria = []

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            logger.debug(f"Braintree: fetching disputes received after {db_incremental_field_last_value}")
            search_criteria.append(
                braintree.DisputeSearch.received_date >= datetime.fromisoformat(db_incremental_field_last_value).date()
            )

        if db_incremental_field_earliest_value:
            logger.debug(f"Braintree: fetching disputes received before {db_incremental_field_earliest_value}")
            search_criteria.append(
                braintree.DisputeSearch.received_date
                < datetime.fromisoformat(db_incremental_field_earliest_value).date()
            )

    if search_criteria:
        disputes = gateway.dispute.search(*search_criteria)
    else:
        logger.debug("Braintree: fetching all disputes")
        disputes = gateway.dispute.search()

    batch = []
    for dispute in disputes:
        serialized = _serialize_braintree_object(dispute)
        batch.append(serialized)

        if len(batch) >= 100:
            yield batch
            batch = []

    if batch:
        yield batch


def _fetch_plans(gateway: braintree.BraintreeGateway, logger: FilteringBoundLogger):
    """Fetch plans from Braintree."""
    logger.debug("Braintree: fetching plans")

    plans = gateway.plan.all()

    batch = []
    for plan in plans:
        serialized = _serialize_braintree_object(plan)
        batch.append(serialized)

        if len(batch) >= 100:
            yield batch
            batch = []

    if batch:
        yield batch


def _fetch_merchant_accounts(gateway: braintree.BraintreeGateway, logger: FilteringBoundLogger):
    """Fetch merchant accounts from Braintree."""
    logger.debug("Braintree: fetching merchant accounts")

    # Merchant accounts don't have a search API, we need to get them individually
    # For now, we'll just return the default merchant account
    try:
        merchant_account = gateway.merchant_account.find(gateway.config.merchant_id)
        serialized = _serialize_braintree_object(merchant_account)
        yield [serialized]
    except Exception as e:
        logger.warning(f"Braintree: failed to fetch merchant account: {e}")
        yield []


def braintree_source(
    merchant_id: str,
    public_key: str,
    private_key: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    db_incremental_field_earliest_value: Any | None = None,
) -> SourceResponse:
    """Main source function for Braintree data extraction."""
    gateway = _get_braintree_gateway(merchant_id, public_key, private_key, environment)

    def get_rows():
        if endpoint == "Transactions":
            yield from _fetch_transactions(
                gateway,
                logger,
                should_use_incremental_field,
                db_incremental_field_last_value,
                db_incremental_field_earliest_value,
            )
        elif endpoint == "Customers":
            yield from _fetch_customers(
                gateway,
                logger,
                should_use_incremental_field,
                db_incremental_field_last_value,
                db_incremental_field_earliest_value,
            )
        elif endpoint == "Subscriptions":
            yield from _fetch_subscriptions(
                gateway,
                logger,
                should_use_incremental_field,
                db_incremental_field_last_value,
                db_incremental_field_earliest_value,
            )
        elif endpoint == "Disputes":
            yield from _fetch_disputes(
                gateway,
                logger,
                should_use_incremental_field,
                db_incremental_field_last_value,
                db_incremental_field_earliest_value,
            )
        elif endpoint == "Plans":
            yield from _fetch_plans(gateway, logger)
        elif endpoint == "MerchantAccounts":
            yield from _fetch_merchant_accounts(gateway, logger)
        else:
            raise ValueError(f"Unknown endpoint: {endpoint}")

    # Determine partition settings based on endpoint
    partition_keys = None
    partition_mode = None
    partition_format = None

    if endpoint in ["Transactions", "Customers", "Subscriptions"]:
        partition_keys = ["created_at"]
        partition_mode = "datetime"
        partition_format = "%Y-%m"
    elif endpoint == "Disputes":
        partition_keys = ["received_date"]
        partition_mode = "datetime"
        partition_format = "%Y-%m"

    return SourceResponse(
        items=get_rows,
        primary_keys=["id"],
        name=endpoint,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_format=partition_format,
    )


def validate_credentials(merchant_id: str, public_key: str, private_key: str, environment: str) -> bool:
    """Validate Braintree credentials by attempting to create a gateway and make a simple API call."""
    try:
        gateway = _get_braintree_gateway(merchant_id, public_key, private_key, environment)

        # Try to search for customers with a limit of 1 to verify credentials
        customers = gateway.customer.search(braintree.CustomerSearch.id != "nonexistent")
        # Just accessing the iterator will verify credentials
        list(customers.items)[:1]

        return True
    except Exception:
        return False
