import json
import datetime as dt
import structlog
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
                if isinstance(event_time, (int, float, str)):
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



def parse_amplitude_event(event_str: str) -> Optional[dict[str, Any]]:
    try:
        entry = json.loads(event_str)
        return parse_amplitude_json(entry)
    except json.JSONDecodeError as e:
        logger.exception("Failed to JSON decode event", error=str(e), event=event_str)
        return None
    except Exception as e:
        logger.exception("Failed to parse event JSON", error=str(e), event=event_str)
        return None


def parse_amplitude_json(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    distinct_id = entry.get("user_id") or entry.get("device_id")
    if not distinct_id:
        logger.error("Missing distinct_id (no user_id or device_id found)", entry=entry)
        return None
        
    event_name = entry["event_type"]

    if event_name == "session_start":
        return None
    if event_name == "[Amplitude] Page Viewed":
        event_name = "$pageview"
    if event_name in ["[Amplitude] Element Clicked", "[Amplitude] Element Changed"]:
        event_name = "$autocapture"

    timestamp = parse_event_timestamp(entry.get("event_time"))

    device_type = entry.get("device_type")
    if device_type == "Windows" or device_type == "Linux":
        device_type = "Desktop"
    elif device_type == "iOS" or device_type == "Android":
        device_type = "Mobile"
    else:
        device_type = None

    payload = {
        "event": event_name,
        "distinct_id": distinct_id,
        "properties": {
            "$os": entry.get("device_type"),
            "$browser": entry.get("os_name"),
            "$browser_version": int(entry.get("os_version")) if entry.get("os_version") else None,
            "$device_type": device_type,
            "$current_url": entry.get("event_properties", {}).get("[Amplitude] Page URL"),
            "$host": entry.get("event_properties", {}).get("[Amplitude] Page Domain"),
            "$pathname": entry.get("event_properties", {}).get("[Amplitude] Page Path"),
            "$viewport_height": entry.get("event_properties", {}).get("[Amplitude] Viewport Height"),
            "$viewport_width": entry.get("event_properties", {}).get("[Amplitude] Viewport Width"),
            "$referrer": entry.get("event_properties", {}).get("referrer"),
            "$referring_domain": entry.get("event_properties", {}).get("referring_domain"),
            "$device_id": entry.get("device_id"),
            "$ip": entry.get("ip_address"),
            "$geoip_city_name": entry.get("city"),
            "$geoip_subdivision_1_name": entry.get("region"),
            "$geoip_country_name": entry.get("country"),
            "$set_once": {
                "$initial_referrer": None
                if entry.get("user_properties", {}).get("initial_referrer") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_referrer"),
                "$initial_referring_domain": None
                if entry.get("user_properties", {}).get("initial_referring_domain") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_referring_domain"),
                "$initial_utm_source": None
                if entry.get("user_properties", {}).get("initial_utm_source") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_utm_source"),
                "$initial_utm_medium": None
                if entry.get("user_properties", {}).get("initial_utm_medium") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_utm_medium"),
                "$initial_utm_campaign": None
                if entry.get("user_properties", {}).get("initial_utm_campaign") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_utm_campaign"),
                "$initial_utm_content": None
                if entry.get("user_properties", {}).get("initial_utm_content") == "EMPTY"
                else entry.get("user_properties", {}).get("initial_utm_content"),
            },
            "$set": {
                "$os": entry.get("device_type"),
                "$browser": entry.get("os_name"),
                "$device_type": device_type,
                "$current_url": entry.get("event_properties", {}).get("[Amplitude] Page URL"),
                "$pathname": entry.get("event_properties", {}).get("[Amplitude] Page Path"),
                "$browser_version": entry.get("os_version"),
                "$referrer": entry.get("event_properties", {}).get("referrer"),
                "$referring_domain": entry.get("event_properties", {}).get("referring_domain"),
                "$geoip_city_name": entry.get("city"),
                "$geoip_subdivision_1_name": entry.get("region"),
                "$geoip_country_name": entry.get("country"),
            },
        },
        "timestamp": timestamp.isoformat(),  # Ensure timestamp is in ISO format for the batch API
    }
    return payload
