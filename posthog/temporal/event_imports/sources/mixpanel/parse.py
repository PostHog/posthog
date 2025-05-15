import json
import structlog
from typing import Optional, Any
from posthog.temporal.event_imports.utils import parse_event_timestamp

logger = structlog.get_logger()


def parse_mixpanel_event(event_str: str) -> Optional[dict[str, Any]]:
    try:
        entry = json.loads(event_str)
        return parse_mixpanel_json(entry)
    except json.JSONDecodeError as e:
        logger.exception("Failed to JSON decode event", error=str(e), event=event_str)
        return None
    except Exception as e:
        logger.exception("Failed to parse event JSON", error=str(e), event=event_str)
        return None


def parse_mixpanel_json(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    properties = entry.get("properties", {})
    if not properties:
        logger.error("Missing properties", entry=entry)
        return None

    distinct_id = properties.get("distinct_id") or properties.get("user_id") or properties.get("device_id")
    if not distinct_id:
        logger.error("Missing distinct_id (no user_id, or device_id found)", entry=entry)
        return None

    event_name = entry["event"]

    if event_name == "$mp_web_page_view":
        event_name = "$pageview"

    timestamp = parse_event_timestamp(properties.get("time"))

    # TODO: need better MixPanel export data to map values to PostHog properties
    payload = {
        "event": event_name,
        "distinct_id": distinct_id,
        "properties": {
            "$os": properties.get("device_type"),
            "$browser": properties.get("os_name"),
            "$geoip_city_name": properties.get("city"),
            "$geoip_subdivision_1_name": properties.get("region"),
            "$geoip_country_name": properties.get("mp_country_code"),
            "$set_once": {},
            "$set": {
                "$os": properties.get("device_type"),
                "$browser": properties.get("os_name"),
                "$geoip_city_name": properties.get("city"),
                "$geoip_subdivision_1_name": properties.get("region"),
                "$geoip_country_name": properties.get("mp_country_code"),
                "$lib": "managed-migrations-mixpanel",
            },
        },
        "timestamp": timestamp.isoformat(),  # Ensure timestamp is in ISO format for the batch API
    }
    return payload
