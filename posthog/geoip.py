from typing import Optional

from django.contrib.gis.geoip2 import GeoIP2

import structlog

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

try:
    geoip: Optional[GeoIP2] = GeoIP2(cache=8)
    # Cache setting corresponds to MODE_MEMORY: Load database into memory. Pure Python.
    # Provides faster performance but uses more memory.
except Exception as e:
    # Inform error tracking, but don't bring down the app
    capture_exception(e)
    geoip = None

VALID_GEOIP_PROPERTIES = [
    "city_name",
    "country_name",
    "country_code",
    "continent_name",
    "continent_code",
    "postal_code",
    "time_zone",
]

# GeoIP2 returns the city name as 'city', but we want to map it to 'city_name'
GEOIP_KEY_MAPPING = {"city": "city_name"}


def get_geoip_properties(ip_address: Optional[str]) -> dict[str, str]:
    """
    Returns a dictionary of geoip properties for the given ip address.

    Contains the following:
        $geoip_city_name
        $geoip_country_name
        $geoip_country_code
        $geoip_continent_name
        $geoip_continent_code
        $geoip_postal_code
        $geoip_time_zone
    """
    if not ip_address or not geoip or ip_address == "127.0.0.1" or ip_address.startswith("192.168."):
        # Local addresses would otherwise throw "The address 127.0.0.1 is not in the database." below
        return {}

    try:
        geoip_properties = geoip.city(ip_address)
    except Exception as e:
        logger.exception(f"geoIP computation error: {e}")
        return {}

    properties = {}
    for key, value in geoip_properties.items():
        if value:
            mapped_key = GEOIP_KEY_MAPPING.get(key, key)
            if mapped_key in VALID_GEOIP_PROPERTIES:
                properties[f"$geoip_{mapped_key}"] = value
    return properties
