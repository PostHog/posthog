from typing import Optional

import structlog
from django.contrib.gis.geoip2 import GeoIP2
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)


try:
    geoip: Optional[GeoIP2] = GeoIP2(cache=8)
    # Cache setting corresponds to MODE_MEMORY: Load database into memory. Pure Python.
    # Provides faster performance but uses more memory.
except Exception as e:
    # Inform Sentry, but don't bring down the app
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
    if not ip_address or not geoip or ip_address == "127.0.0.1":
        # "127.0.0.1" would throw "The address 127.0.0.1 is not in the database." below
        return {}

    try:
        geoip_properties = geoip.city(ip_address)
    except Exception as e:
        logger.exception(f"geoIP computation error: {e}")
        return {}

    properties = {}
    for key, value in geoip_properties.items():
        if value and key in VALID_GEOIP_PROPERTIES:
            properties[f"$geoip_{key}"] = value
    return properties
