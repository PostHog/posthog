import ipaddress
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Optional, TypedDict

from django.contrib.gis.geoip2 import GeoIP2

import structlog
from geoip2.errors import AddressNotFoundError
from prometheus_client import Counter

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

# Distinct addresses whose location we keep per process. A MaxMind lookup costs ~75us even with the
# database in memory, and the risk middleware does one per authenticated request, so the working set
# of active client addresses is worth holding onto. Each entry is a few hundred bytes.
GEOIP_LOCATION_CACHE_SIZE = 4096

# Only genuine lookup failures increment this counter. Non-public ranges have no location by definition,
# so skipping them keeps the counter low-volume and actionable.
GEOIP_LOOKUP_FAILURES = Counter(
    "geoip_lookup_failures_total",
    "GeoIP city lookups that returned no location, by failure reason.",
    labelnames=["reason"],
)

type IPClassification = Literal[
    "public",
    "invalid",
    "private",
    "loopback",
    "link_local",
    "reserved",
    "unspecified",
    "multicast",
    "shared",
    "site_local",
]

_NON_PUBLIC_IP_CATEGORIES: frozenset[IPClassification] = frozenset(
    {"private", "loopback", "link_local", "reserved", "unspecified", "multicast", "shared", "site_local"}
)

# RFC 6598 shared address space, which Python reports as neither private nor reserved.
_SHARED_ADDRESS_SPACE = ipaddress.IPv4Network("100.64.0.0/10")


def _classify_ip(ip_address: str) -> IPClassification:
    """Classify an address before a GeoIP lookup.

    The order is significant because Python also reports loopback, link-local, reserved, and
    unspecified addresses as private.
    """
    try:
        parsed = ipaddress.ip_address(ip_address)
    except ValueError:
        return "invalid"
    if parsed.is_unspecified:
        return "unspecified"
    if parsed.is_loopback:
        return "loopback"
    if parsed.is_link_local:
        return "link_local"
    if parsed.is_reserved:
        return "reserved"
    if parsed.is_private:
        return "private"
    # Python's private and reserved predicates miss these three, and none of them can have a location:
    # multicast is never a unicast source, RFC 6598 shared space sits behind a carrier or cloud NAT, and
    # RFC 3879 deprecated IPv6 site-local.
    if parsed.is_multicast:
        return "multicast"
    if parsed in _SHARED_ADDRESS_SPACE:
        return "shared"
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.is_site_local:
        return "site_local"
    return "public"


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
    if not ip_address or not geoip:
        return {}

    category = _classify_ip(ip_address)
    if category in _NON_PUBLIC_IP_CATEGORIES:
        return {}
    if category == "invalid":
        GEOIP_LOOKUP_FAILURES.labels(reason="invalid").inc()
        return {}

    try:
        geoip_properties = geoip.city(ip_address)
    except AddressNotFoundError:
        # A public address missing from the database is a coverage gap, not an operational error.
        GEOIP_LOOKUP_FAILURES.labels(reason="not_found").inc()
        return {}
    except Exception:
        GEOIP_LOOKUP_FAILURES.labels(reason="lookup_error").inc()
        logger.exception("geoIP computation error")
        return {}

    properties: dict[str, str] = {}
    for key, value in geoip_properties.items():
        if isinstance(value, str) and value:
            mapped_key = GEOIP_KEY_MAPPING.get(key, key)
            if mapped_key in VALID_GEOIP_PROPERTIES:
                properties[f"$geoip_{mapped_key}"] = value
    return properties


class GeoLocation(TypedDict, total=False):
    latitude: float
    longitude: float
    country_code: str


def _is_non_public_ip(ip_address: str) -> bool:
    """True for addresses geoip can't usefully locate — private/reserved ranges (incl. IPv6) and
    malformed input. Without this, RFC1918 (10/8, 172.16/12), loopback (::1), link-local, etc. would
    fall through to geoip.city() and raise "not in the database" on every such request."""
    return _classify_ip(ip_address) != "public"


@dataclass(frozen=True, kw_only=True)
class CachedLocation:
    """One memoized geoip result. Keyword-only because latitude and longitude share a type and would
    otherwise be swappable at the call site."""

    latitude: Optional[float]
    longitude: Optional[float]
    country_code: Optional[str]


@lru_cache(maxsize=GEOIP_LOCATION_CACHE_SIZE)
def _lookup_location(ip_address: str) -> CachedLocation:
    """Cached lookup behind get_geoip_location, which runs on every authenticated request.

    The database is opened once at import and never written, so the mapping from address to location
    cannot change under a running process — a deploy shipping a new database restarts it. Frozen, so a
    cached entry can't be mutated through one caller and observed by the next. A public address the
    database does not cover is memoized as an empty location, so a repeat request for it does not pay
    the lookup again. Other failures raise, and lru_cache doesn't store exceptions, so those are retried
    rather than pinned for the life of the process.
    """
    assert geoip is not None  # caller checks; keeps the cached path free of the None branch
    try:
        city = geoip.city(ip_address)
    except AddressNotFoundError:
        # A public address missing from the database is a coverage gap, not an operational error.
        GEOIP_LOOKUP_FAILURES.labels(reason="not_found").inc()
        return CachedLocation(latitude=None, longitude=None, country_code=None)
    latitude = city.get("latitude")
    longitude = city.get("longitude")
    country_code = city.get("country_code")
    return CachedLocation(
        latitude=float(latitude) if isinstance(latitude, int | float) else None,
        longitude=float(longitude) if isinstance(longitude, int | float) else None,
        country_code=country_code if isinstance(country_code, str) else None,
    )


def get_geoip_location(ip_address: Optional[str]) -> GeoLocation:
    """Latitude/longitude/country_code for risk scoring. Unlike get_geoip_properties this keeps floats."""
    if not ip_address or not geoip or _is_non_public_ip(ip_address):
        return {}
    try:
        location = _lookup_location(ip_address)
    except Exception:
        GEOIP_LOOKUP_FAILURES.labels(reason="lookup_error").inc()
        logger.exception("geoIP location error")
        return {}
    out: GeoLocation = {}
    if location.latitude is not None:
        out["latitude"] = location.latitude
    if location.longitude is not None:
        out["longitude"] = location.longitude
    if location.country_code is not None:
        out["country_code"] = location.country_code
    return out
