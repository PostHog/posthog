from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

import structlog
from celery import shared_task
from retry import retry

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.logging.timing import timed_log
from posthog.models.organization import Organization
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team.team import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Query settings and retry configuration (similar to usage_report.py)
CH_BILLING_SETTINGS = {
    "max_execution_time": 5 * 60,  # 5 minutes
}

QUERY_RETRIES = 3
QUERY_RETRY_DELAY = 1
QUERY_RETRY_BACKOFF = 2

# Valid product types that can be activated (based on ProductIntent.activation_checks)
VALID_PRODUCT_TYPES = [
    "product_analytics",
    "session_replay",
    "feature_flags",
    "experiments",
    "surveys",
    "error_tracking",
    "data_warehouse",
]


def execute_custom_query(
    query_template: str,
    params: dict[str, Any],
    workload: Workload = Workload.OFFLINE,
    settings: dict[str, Any] | None = None,
) -> list[Any]:
    """
    Execute a custom SQL query against ClickHouse.

    Args:
        query_template: SQL query template with %(param_name)s placeholders
        params: Dictionary of parameters to substitute in the query
        workload: Workload type (default: OFFLINE for batch queries)
        settings: Additional ClickHouse settings (defaults to CH_BILLING_SETTINGS)

    Returns:
        Query results as a list

    Example:
        # Use triple-quoted strings for multi-line SQL queries
        query_template = "SELECT team_id, count() FROM events WHERE timestamp >= %(begin)s AND timestamp < %(end)s GROUP BY team_id"
        results = execute_custom_query(query_template, {"begin": start_date, "end": end_date})
    """
    if settings is None:
        settings = CH_BILLING_SETTINGS

    return sync_execute(
        query_template,
        params,
        workload=workload,
        settings=settings,
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def execute_custom_query_with_retry(
    query_template: str,
    params: dict[str, Any],
    workload: Workload = Workload.OFFLINE,
    settings: dict[str, Any] | None = None,
) -> list[Any]:
    """
    Execute a custom SQL query against ClickHouse with retry logic and timing.

    Use this for queries that might fail due to transient issues.

    Args:
        query_template: SQL query template with %(param_name)s placeholders
        params: Dictionary of parameters to substitute in the query
        workload: Workload type (default: OFFLINE for batch queries)
        settings: Additional ClickHouse settings (defaults to CH_BILLING_SETTINGS)

    Returns:
        Query results as a list
    """
    return execute_custom_query(query_template, params, workload, settings)


def _execute_split_query(
    begin: datetime,
    end: datetime,
    query_template: str,
    params: dict[str, Any],
    num_splits: int = 2,
    combine_results_func: Optional[Callable[[list], Any]] = None,
) -> Any:
    """
    Helper function to execute a query split into multiple parts to reduce load.
    Splits the time period into num_splits parts and runs separate queries, then combines the results.

    Args:
        begin: Start of the time period
        end: End of the time period
        query_template: SQL query template with %(begin)s and %(end)s placeholders
        params: Additional parameters for the query
        num_splits: Number of time splits to make (default: 2)
        combine_results_func: Optional function to combine results from multiple queries
                             If None, uses the default team_id count combiner

    Returns:
        Combined query results
    """
    # Calculate the time interval for each split
    time_delta = (end - begin) / num_splits

    all_results = []

    # Execute query for each time split
    for i in range(num_splits):
        split_begin = begin + (time_delta * i)
        split_end = begin + (time_delta * (i + 1))

        # For the last split, use the exact end time to avoid rounding issues
        if i == num_splits - 1:
            split_end = end

        # Create a copy of params and update with the split time range
        split_params = params.copy()
        split_params["begin"] = split_begin
        split_params["end"] = split_end

        # Execute the query for this time split
        split_result = sync_execute(
            query_template,
            split_params,
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )

        all_results.append(split_result)

    # If no custom combine function is provided, use the default team_id count combiner
    if combine_results_func is None:
        return _combine_team_count_results(all_results)
    else:
        return combine_results_func(all_results)


def _combine_team_count_results(results_list: list) -> list[tuple[int, int]]:
    """
    Default function to combine results from multiple queries that return (team_id, count) tuples.

    Args:
        results_list: List of query results, each containing (team_id, count) tuples

    Returns:
        Combined list of (team_id, count) tuples
    """
    team_counts: dict[int, int] = {}

    # Combine all results
    for results in results_list:
        for team_id, count in results:
            if team_id in team_counts:
                team_counts[team_id] += count
            else:
                team_counts[team_id] = count

    # Convert back to the expected format
    return list(team_counts.items())


def get_org_activated_products(organization: Organization) -> tuple[list[str], str]:
    """
    Get the ordered list of activated products for an organization.

    Returns:
        Tuple of (sorted product list, product combo key)
        The combo key is a sorted, comma-separated string for easy comparison
    """
    # Get all teams for this organization (excluding demo teams)
    teams = Team.objects.filter(organization=organization, is_demo=False)

    # Get all activated products across all teams in this org
    activated_intents = ProductIntent.objects.filter(
        team__in=teams,
        activated_at__isnull=False,
        product_type__in=VALID_PRODUCT_TYPES,
    ).order_by("activated_at")

    # Get unique product types (sorted for consistency)
    products = sorted({intent.product_type for intent in activated_intents})

    # Create combo key (sorted, comma-separated)
    combo_key = ",".join(products) if products else ""

    return products, combo_key


def count_product_combos() -> dict[str, int]:
    """
    Count and sort product combos across all organizations.

    Returns:
        Dictionary mapping combo key (sorted products) to count of orgs with that combo
    """
    org_combos: list[str] = []

    # Get all orgs except internal metrics ones
    # Note: is_demo is a Team field, not Organization field, so we filter teams separately in get_org_activated_products
    organizations = Organization.objects.exclude(for_internal_metrics=True).only("id")

    logger.info("Counting product combos", org_count=organizations.count())

    for org in organizations:
        _, combo_key = get_org_activated_products(org)
        if combo_key:  # Only count orgs with at least one activated product
            org_combos.append(combo_key)

    # Count occurrences
    combo_counts = dict(Counter(org_combos))

    # Sort by count (descending) for logging
    sorted_combos = sorted(combo_counts.items(), key=lambda x: x[1], reverse=True)

    logger.info(
        "Product combo counts complete",
        total_combos=len(combo_counts),
        top_combos=sorted_combos[:10],  # Log top 10
    )

    return combo_counts


def find_next_best_product(current_products: list[str], combo_counts: dict[str, int]) -> Optional[str]:
    """
    Given an org's current product combo, find the next closest combo with one additional product.

    Args:
        current_products: List of currently activated products (sorted)
        combo_counts: Dictionary of combo keys to counts

    Returns:
        The recommended product or None if no recommendation found
    """
    current_combo_key = ",".join(current_products) if current_products else ""

    # Find all combos that contain the current combo plus one additional product
    candidates: list[tuple[str, int]] = []

    for combo_key, count in combo_counts.items():
        if not combo_key or combo_key == current_combo_key:
            continue

        combo_products = combo_key.split(",")

        # Check if this combo contains all current products plus exactly one more
        if len(combo_products) == len(current_products) + 1:
            if all(product in combo_products for product in current_products):
                # This is a valid candidate - find the additional product
                additional_product = [p for p in combo_products if p not in current_products]
                if len(additional_product) == 1:
                    candidates.append((additional_product[0], count))

    if not candidates:
        return None

    # Sort by count (descending) - recommend the most common next product
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Return the most common one
    recommended_product, _ = candidates[0]

    return recommended_product


def calculate_and_store_recommendations(combo_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """
    Calculate next best product recommendations for all organizations and store them.

    Args:
        combo_counts: Pre-calculated combo counts (will be calculated if None)

    Returns:
        Dictionary with statistics about recommendations
    """
    if combo_counts is None:
        combo_counts = count_product_combos()

    # Get all orgs except internal metrics ones
    # Note: is_demo is a Team field, not Organization field, so we filter teams separately in get_org_activated_products
    organizations = Organization.objects.exclude(for_internal_metrics=True).only("id")

    recommendations: dict[str, str | None] = {}
    stats = {
        "total_orgs": 0,
        "orgs_with_products": 0,
        "orgs_with_recommendations": 0,
        "no_recommendation_found": 0,
        "product_recommendations": Counter(),
    }

    logger.info("Calculating recommendations", org_count=organizations.count())

    for org in organizations:
        stats["total_orgs"] += 1
        current_products, combo_key = get_org_activated_products(org)

        if not current_products:
            # No activated products yet - skip for now (could recommend "product_analytics" as default)
            continue

        stats["orgs_with_products"] += 1

        # Find next best product
        recommended_product = find_next_best_product(current_products, combo_counts)

        if recommended_product:
            recommendations[str(org.id)] = recommended_product
            stats["orgs_with_recommendations"] += 1
            stats["product_recommendations"][recommended_product] += 1

            store_recommendation(org, recommended_product, current_products)
        else:
            stats["no_recommendation_found"] += 1
            # Clear any existing recommendation
            clear_recommendation(org)

    logger.info(
        "Recommendations complete",
        total_orgs=stats["total_orgs"],
        orgs_with_products=stats["orgs_with_products"],
        orgs_with_recommendations=stats["orgs_with_recommendations"],
        top_recommendations=stats["product_recommendations"].most_common(10),
    )

    return stats


def store_recommendation(organization: Organization, recommended_product: str, current_products: list[str]) -> None:
    """
    Store the recommendation for an organization.

    Uses the ProductRecommendation model to store the recommendation.
    """
    from posthog.models.product_recommendation import ProductRecommendation

    recommendation, created = ProductRecommendation.objects.update_or_create(
        organization=organization,
        defaults={
            "recommended_product": recommended_product,
            "product_sequence_state_before": list(current_products),
            "num_products_before": len(current_products),
            "calculated_at": datetime.now(UTC),
        },
    )

    logger.debug(
        "Stored recommendation",
        org_id=str(organization.id),
        product=recommended_product,
        created=created,
    )


def clear_recommendation(organization: Organization) -> None:
    """Clear any existing recommendation for an organization."""
    from posthog.models.product_recommendation import ProductRecommendation

    ProductRecommendation.objects.filter(organization=organization).delete()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=3,
    default_retry_delay=300,
)
def calculate_product_recommendations_for_orgs() -> dict[str, Any]:
    """
    Calculate next best product recommendations for all organizations.

    This task:
    1. Counts and sorts product combos across all orgs
    2. For each org, finds the next closest combo with one additional product
    3. Stores the recommendation

    Run on a regular cadence (e.g., daily).
    """
    try:
        logger.info("Starting product recommendations calculation")

        # Step 1: Count and sort product combos
        combo_counts = count_product_combos()

        # Step 2 & 3: Calculate and store recommendations
        stats = calculate_and_store_recommendations(combo_counts)

        logger.info("Product recommendations calculation complete", **stats)

        return stats

    except Exception as e:
        logger.exception("Failed to calculate product recommendations", error=str(e))
        raise
