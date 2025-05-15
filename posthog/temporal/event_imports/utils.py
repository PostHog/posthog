import datetime as dt
import structlog
import requests
from typing import Optional, Any

logger = structlog.get_logger()


def parse_event_timestamp(event_time) -> dt.datetime:
    """
    Parse event timestamp from various formats.
    Handles string formats, unix timestamps, and provides fallbacks.
    Args:
        event_time: The timestamp value from the event
    Returns:
        dt.datetime: The parsed datetime object
    """
    try:
        # First try to parse as string format
        timestamp = dt.datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S.%f")
    except (ValueError, TypeError):
        try:
            # If that fails, try parsing without microseconds
            timestamp = dt.datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                # If that fails, try to parse as Unix timestamp (in milliseconds)
                if isinstance(event_time, int | float | str):
                    # Convert to float, divide by 1000 if it's milliseconds
                    event_time_float = float(event_time)
                    # Amplitude uses milliseconds for timestamps
                    if event_time_float > 1e11:  # Large enough to be in milliseconds
                        event_time_float /= 1000
                    timestamp = dt.datetime.fromtimestamp(event_time_float)
                else:
                    # Fallback to current time
                    logger.warning("Unknown timestamp format, using current time", event_time=event_time)
                    timestamp = dt.datetime.now()
            except (ValueError, TypeError, OverflowError):
                logger.warning("Failed to parse timestamp, using current time", event_time=event_time)
                timestamp = dt.datetime.now()

    # Sanity check - don't allow future timestamps
    if timestamp > dt.datetime.now():
        logger.warning("Future timestamp detected, using current time", original_timestamp=timestamp)
        timestamp = dt.datetime.now()

    return timestamp


def send_event_batch(batch: list[dict[str, Any]], posthog_api_key: str, posthog_domain: Optional[str] = None) -> int:
    """
    Sends a batch of events to PostHog.
    Args:
        batch: List of events to send
        posthog_api_key: PostHog API key
        posthog_domain: PostHog domain (defaults to 'https://app.dev.posthog.com')
    Returns:
        Number of events processed
    """
    if not batch:
        return 0

    logger = structlog.get_logger()

    url = f"{posthog_domain or 'https://app.dev.posthog.com'}/batch/"
    headers = {"Content-Type": "application/json"}
    payload = {"api_key": posthog_api_key, "historical_migration": True, "batch": batch}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        if len(batch) > 1:
            logger.info(f"Sent batch of {len(batch)} events to PostHog. Status: {response.status_code}")
        else:
            logger.info(f"Sent final event to PostHog. Status: {response.status_code}")

        return len(batch)
    except requests.exceptions.RequestException as e:
        logger.exception(f"Failed to send batch to PostHog: {str(e)}")
        if hasattr(e, "response") and e.response:
            logger.exception(f"Response status: {e.response.status_code}, Response body: {e.response.text[:500]}")
        return 0
