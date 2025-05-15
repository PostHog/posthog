import logging
from datetime import datetime, timedelta
from typing import Optional

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.betting import BetDefinition, ProbabilityDistribution
from posthog.clickhouse.client.connection import Workload

logger = logging.getLogger(__name__)


def load_pageview_probability_distribution(
    bet_definition: BetDefinition, interval_days: int = 30
) -> list[dict[str, float]]:
    """
    Load historical pageview data from ClickHouse to create a probability distribution.
    Uses linear regression to predict future values based on historical trends.
    Groups data by the probability_distribution_interval and predicts out to the closing_date.

    Args:
        bet_definition: The bet definition to create a probability distribution for
        interval_days: Number of days to look back for historical data

    Returns:
        A list of buckets with values and probabilities
    """
    team_id = bet_definition.team_id

    # Get parameters from bet definition
    bet_params = bet_definition.bet_parameters
    url_pattern = bet_params.get("url", None)
    filters = bet_params.get("filters", {})

    # Get the interval in seconds from the bet definition
    interval_seconds = bet_definition.probability_distribution_interval

    # Convert to hours for easier handling in the query
    interval_hours = max(1, interval_seconds // 3600)  # Minimum 1 hour interval

    # Build the query based on bet parameters and interval
    query = f"""
        SELECT
            toStartOfInterval(timestamp, INTERVAL {interval_hours} HOUR) AS interval_start,
            count() AS pageview_count
        FROM events
        WHERE team_id = %(team_id)s
            AND event = '$pageview'
            AND timestamp >= %(start_date)s
            AND timestamp < %(end_date)s
    """

    # Add URL filter if specified
    if url_pattern:
        query += " AND properties.$current_url LIKE %(url_pattern)s"

    # Add additional filters if specified
    filter_conditions = []
    filter_params = {}

    for filter_key, filter_values in filters.items():
        if isinstance(filter_values, list) and filter_values:
            placeholder = f"{filter_key}_values"
            filter_conditions.append(f"properties.{filter_key} IN %(${placeholder})s")
            filter_params[f"${placeholder}"] = filter_values

    if filter_conditions:
        query += " AND " + " AND ".join(filter_conditions)

    # Group by interval and order
    query += """
        GROUP BY interval_start
        ORDER BY interval_start
    """

    # Prepare parameters for the query
    end_date = datetime.now()
    start_date = end_date - timedelta(days=interval_days)

    params = {
        "team_id": team_id,
        "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
        **({"url_pattern": f"%{url_pattern}%"} if url_pattern else {}),
        **filter_params,
    }

    # Execute the query
    try:
        results = sync_execute(query, params, workload=Workload.ONLINE, team_id=team_id)

        if not results:
            logger.warning(f"No pageview data found for bet definition {bet_definition.id}")
            return []

        # Process results into time series data
        intervals = []
        interval_counts = []

        for interval_start, count in results:
            # Convert interval to hours since start for regression
            if isinstance(interval_start, str):
                interval_dt = datetime.strptime(interval_start, "%Y-%m-%d %H:%M:%S")
            else:
                interval_dt = interval_start

            hours_since_start = (interval_dt - start_date.replace(tzinfo=None)).total_seconds() / 3600
            intervals.append(hours_since_start)
            interval_counts.append(count)

        # Calculate how many intervals to predict until the closing date
        hours_until_closing = 0
        if bet_definition.closing_date:
            hours_until_closing = max(0, (bet_definition.closing_date - end_date).total_seconds() / 3600)

        # Use linear regression to predict future values up to the closing date
        prediction_intervals = (
            int(hours_until_closing / interval_hours) + 1
        )  # +1 to ensure we go at least to closing date
        predicted_values = predict_future_values(intervals, interval_counts, prediction_intervals=prediction_intervals)

        # Use the bucket definitions from the bet definition
        return create_distribution_buckets_from_definition(predicted_values, bet_definition.bucket_definitions)

    except Exception as e:
        logger.exception(f"Error loading pageview data for bet definition {bet_definition.id}: {e}")
        return []


def predict_future_values(intervals: list[float], values: list[int], prediction_intervals: int = 24) -> list[int]:
    """
    Use linear regression to predict future values based on historical data.

    Args:
        intervals: List of time intervals (as floats, e.g., hours since start)
        values: List of historical values corresponding to intervals
        prediction_intervals: Number of intervals to predict into the future

    Returns:
        List of predicted values including historical and future values
    """
    if not intervals or not values or len(intervals) < 2:
        return values  # Not enough data for regression

    # Simple linear regression to find slope and intercept
    n = len(intervals)
    sum_x = sum(intervals)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(intervals, values))
    sum_xx = sum(x * x for x in intervals)

    # Calculate slope and intercept
    # Formula: slope = (n*sum_xy - sum_x*sum_y) / (n*sum_xx - sum_x*sum_x)
    # Formula: intercept = (sum_y - slope*sum_x) / n
    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:  # Avoid division by zero
        slope = 0
    else:
        slope = (n * sum_xy - sum_x * sum_y) / denominator

    intercept = (sum_y - slope * sum_x) / n if n > 0 else 0

    # Determine the average interval size to use for predictions
    if len(intervals) >= 2:
        # Calculate average difference between consecutive intervals
        sorted_intervals = sorted(intervals)
        interval_diffs = [sorted_intervals[i + 1] - sorted_intervals[i] for i in range(len(sorted_intervals) - 1)]
        avg_interval = sum(interval_diffs) / len(interval_diffs) if interval_diffs else 1.0
    else:
        avg_interval = 1.0  # Default to 1 hour if we can't determine

    # Predict future values
    last_interval = max(intervals)
    future_intervals = [last_interval + (i + 1) * avg_interval for i in range(prediction_intervals)]
    future_predictions = [max(0, round(slope * x + intercept)) for x in future_intervals]

    # Combine historical and predicted values
    all_predictions = values + future_predictions

    return all_predictions


def generate_bucket_definitions(values: list[int], num_buckets: int = 5) -> list[dict[str, int]]:
    """
    Generate bucket definitions based on the distribution of values.
    Creates buckets that better represent the actual data distribution.

    Args:
        values: List of values to base the buckets on
        num_buckets: Number of buckets to create (default: 5)

    Returns:
        A list of bucket definitions with min and max values
    """
    if not values or len(values) < num_buckets:
        # Default buckets if no data or not enough data points
        return [{"min": i * 100, "max": (i + 1) * 100 - 1} for i in range(num_buckets)]

    # Sort values to analyze distribution
    sorted_values = sorted(values)

    # Use percentiles to create buckets that better represent the distribution
    bucket_definitions = []

    # Calculate the number of values per bucket
    values_per_bucket = len(sorted_values) // num_buckets
    remainder = len(sorted_values) % num_buckets

    current_idx = 0

    for i in range(num_buckets):
        # Distribute the remainder across the first few buckets
        bucket_size = values_per_bucket + (1 if i < remainder else 0)

        if bucket_size == 0:
            # Handle edge case where we have more buckets than values
            continue

        start_idx = current_idx
        end_idx = min(current_idx + bucket_size - 1, len(sorted_values) - 1)

        min_value = sorted_values[start_idx]
        max_value = sorted_values[end_idx]

        # Ensure no overlap between buckets
        if bucket_definitions and min_value <= bucket_definitions[-1]["max"]:
            min_value = bucket_definitions[-1]["max"] + 1

        # Ensure min <= max
        if min_value > max_value:
            max_value = min_value

        bucket_definitions.append({"min": min_value, "max": max_value})

        current_idx = end_idx + 1

    # Handle edge case where we didn't use all values
    if current_idx < len(sorted_values) and bucket_definitions:
        bucket_definitions[-1]["max"] = max(bucket_definitions[-1]["max"], sorted_values[-1])

    return bucket_definitions


def create_distribution_buckets_from_definition(
    values: list[int], bucket_definitions: list[dict[str, int]]
) -> list[dict[str, float]]:
    """
    Create probability distribution buckets using predefined bucket definitions.

    Args:
        values: List of values to distribute into buckets
        bucket_definitions: List of bucket definitions with min and max values

    Returns:
        A list of buckets with values and probabilities
    """
    if not values or not bucket_definitions:
        return []

    # Initialize buckets with zero counts
    buckets = []
    for bucket_def in bucket_definitions:
        min_val = bucket_def.get("min", 0)
        max_val = bucket_def.get("max", 0)

        # Use the midpoint as the representative value
        value = (min_val + max_val) // 2

        buckets.append({"value": value, "min": min_val, "max": max_val, "count": 0})

    # Count values in each bucket
    total_values = len(values)
    for val in values:
        for bucket in buckets:
            if bucket["min"] <= val <= bucket["max"]:
                bucket["count"] += 1
                break
        else:
            # If value doesn't fit in any bucket, add it to the closest one
            closest_bucket = min(buckets, key=lambda b: min(abs(val - b["min"]), abs(val - b["max"])))
            closest_bucket["count"] += 1

    # Calculate probabilities
    for bucket in buckets:
        bucket["probability"] = round(bucket["count"] / total_values, 3) if total_values > 0 else 0
        # Remove the count as it's not needed in the final distribution
        bucket.pop("count", None)

    # Ensure probabilities sum to 1.0
    total_probability = sum(bucket["probability"] for bucket in buckets)
    if total_probability > 0 and total_probability != 1.0:
        # Normalize probabilities
        for bucket in buckets:
            bucket["probability"] = round(bucket["probability"] / total_probability, 3)

        # Handle any rounding errors by adjusting the last bucket
        adjustment = 1.0 - sum(bucket["probability"] for bucket in buckets)
        if adjustment != 0:
            buckets[-1]["probability"] = round(buckets[-1]["probability"] + adjustment, 3)

    return buckets


def create_probability_distribution(bet_definition: BetDefinition) -> Optional[ProbabilityDistribution]:
    """
    Create a probability distribution for a bet definition based on its type.
    Always generates bucket definitions based on actual data distribution.

    Args:
        bet_definition: The bet definition to create a probability distribution for

    Returns:
        A new ProbabilityDistribution object or None if creation failed

    Raises:
        ValueError: If the bet type is not supported
    """
    # Check if the bet type is supported
    supported_types = [BetDefinition.BetType.PAGEVIEWS]
    if bet_definition.type not in supported_types:
        raise ValueError(
            f"Bet type '{bet_definition.type}' is not supported. Supported types: {', '.join(supported_types)}"
        )

    # First get historical data to base the buckets on
    if bet_definition.type == BetDefinition.BetType.PAGEVIEWS:
        # Query raw data to generate buckets
        team_id = bet_definition.team_id
        bet_params = bet_definition.bet_parameters
        url_pattern = bet_params.get("url", None)

        # Simple query to get recent pageview counts
        query = """
            SELECT
                toDate(timestamp) AS date,
                count() AS pageview_count
            FROM events
            WHERE team_id = %(team_id)s
                AND event = '$pageview'
                AND timestamp >= %(start_date)s
        """

        if url_pattern:
            query += " AND properties.$current_url LIKE %(url_pattern)s"

        query += " GROUP BY date ORDER BY date"

        # Look back 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        params = {
            "team_id": team_id,
            "start_date": start_date.strftime("%Y-%m-%d"),
            **({"url_pattern": f"%{url_pattern}%"} if url_pattern else {}),
        }

        try:
            results = sync_execute(query, params, workload=Workload.ONLINE, team_id=team_id)
            daily_counts = [count for _, count in results]

            # Only generate and save bucket definitions if they don't already exist
            # This ensures we maintain consistent buckets across refreshes
            if not bet_definition.bucket_definitions:
                # Generate bucket definitions based on the data distribution
                # Use 5 buckets as requested
                bucket_definitions = generate_bucket_definitions(daily_counts, num_buckets=5)

                # Save the bucket definitions to the bet definition
                bet_definition.bucket_definitions = bucket_definitions
                bet_definition.save(update_fields=["bucket_definitions"])

            # Now create the probability distribution using these bucket definitions
            distribution_data = load_pageview_probability_distribution(bet_definition)

            if not distribution_data:
                logger.warning(f"Failed to create probability distribution for bet definition {bet_definition.id}")
                return None

            # Create and save the probability distribution
            probability_distribution = ProbabilityDistribution.objects.create(
                bet_definition=bet_definition, distribution_data=distribution_data
            )
            return probability_distribution

        except Exception as e:
            logger.exception(f"Error generating bucket definitions for bet definition {bet_definition.id}: {e}")
            # Use default bucket definitions if we couldn't get data
            bucket_definitions = generate_bucket_definitions([], num_buckets=5)
            bet_definition.bucket_definitions = bucket_definitions
            bet_definition.save(update_fields=["bucket_definitions"])

    # Handle other bet types here as they are supported

    # If we get here, either we have a non-pageview bet type or there was an error
    # Try to create a distribution anyway
    try:
        if bet_definition.type == BetDefinition.BetType.PAGEVIEWS:
            distribution_data = load_pageview_probability_distribution(bet_definition)

            if distribution_data:
                probability_distribution = ProbabilityDistribution.objects.create(
                    bet_definition=bet_definition, distribution_data=distribution_data
                )
                return probability_distribution
    except Exception as e:
        logger.exception(f"Error saving probability distribution for bet definition {bet_definition.id}: {e}")

    return None


def refresh_probability_distribution(bet_definition_id: str) -> Optional[ProbabilityDistribution]:
    """
    Refresh the probability distribution for a bet definition.

    Args:
        bet_definition_id: The ID of the bet definition to refresh

    Returns:
        The updated ProbabilityDistribution object or None if refresh failed
    """
    try:
        bet_definition = BetDefinition.objects.get(id=bet_definition_id)

        # Only refresh active bet definitions
        if not bet_definition.is_active:
            logger.info(f"Skipping refresh for inactive bet definition {bet_definition_id}")
            return None

        return create_probability_distribution(bet_definition)
    except BetDefinition.DoesNotExist:
        logger.exception(f"Bet definition {bet_definition_id} not found")
        return None
    except Exception as e:
        logger.exception(f"Error refreshing probability distribution for bet definition {bet_definition_id}: {e}")
        return None
