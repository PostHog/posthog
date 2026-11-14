"""The GeoIP transformation (`template-geoip`), ported to Python for backfills.

`GeoipEnrichment.apply` returns the properties that the transformation in
`nodejs/src/cdp/templates/_transformations/geoip/geoip.template.ts` returns for the same event and the
same MMDB file. Records are in the raw MaxMind shape (snake_case), where the template reads the camelCase
shape of geoip2-node. `tests/fixtures/geoip_template_parity*.json` hold the output of each shipped
template version for each test case. A backfill that writes different keys or values than ingestion
would leave events that disagree with their neighbours.
"""

import hashlib
import ipaddress
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import geoip2.errors
import geoip2.database

from posthog.dataclasses import frozen

# The template's `geoipProperties`, in its order, which is the key order of `$set` and `$set_once`.
GEOIP_KEYS: tuple[str, ...] = (
    "city_name",
    "city_confidence",
    "subdivision_2_name",
    "subdivision_2_code",
    "subdivision_1_name",
    "subdivision_1_code",
    "country_name",
    "country_code",
    "continent_name",
    "continent_code",
    "postal_code",
    "latitude",
    "longitude",
    "accuracy_radius",
    "time_zone",
)

INITIAL_GEOIP_PREFIX = "$initial_geoip_"
GEOIP_PREFIX = "$geoip_"

_LOCAL_DEVELOPMENT_IP = "89.160.20.129"

GeoipRecord = Mapping[str, Any]
GeoipLookup = Callable[[str], GeoipRecord | None]


@frozen
class GeoipTemplateVersion:
    """A shipped source of the template. A function keeps the source it was saved with."""

    source_sha256: str
    shipped: str
    remaps_private_network: bool


# The hashes match NOOP_SOURCE_HASHES in nodejs/src/cdp/hog-transformations/geoip-noop.ts.
TEMPLATE_VERSIONS: tuple[GeoipTemplateVersion, ...] = (
    GeoipTemplateVersion(
        source_sha256="c60a2c9cf0d2f82812392c3c682f4223e17082f109e02fbf5467fbb0069d0770",
        shipped="2025-01-30",
        remaps_private_network=False,
    ),
    GeoipTemplateVersion(
        source_sha256="936b06d7d65914d43e5b9f45d8eecda36450e0c128bbfb522020fc0600261175",
        shipped="2026-01-08",
        remaps_private_network=True,
    ),
)


def template_version(hog_source: str) -> GeoipTemplateVersion | None:
    """The shipped version a function's Hog source is, or None for an edited or unknown source."""
    # Saving a function trims these characters, as `trimLikeSave` in geoip-noop.ts does.
    digest = hashlib.sha256(hog_source.strip(" \t\r\n").encode()).hexdigest()
    return next((version for version in TEMPLATE_VERSIONS if version.source_sha256 == digest), None)


@frozen
class GeoipEnrichment:
    """What the template adds to one event.

    `location` holds the `$geoip_*` keys of the event properties. `set_properties` and `set_once_properties`
    hold the keys the template adds to `$set` and `$set_once`.
    """

    location: dict[str, Any]
    set_properties: dict[str, Any]
    set_once_properties: dict[str, Any]

    def apply(self, properties: Mapping[str, Any]) -> dict[str, Any]:
        """The event properties after the template ran on them."""
        enriched = dict(properties)
        enriched["$set"] = {**(_object_or_empty(properties.get("$set"))), **self.set_properties}
        enriched["$set_once"] = {**(_object_or_empty(properties.get("$set_once"))), **self.set_once_properties}
        enriched.update(self.location)
        return enriched


class MmdbGeoipLookup:
    """City lookups against an MMDB file, returning `None` where geoip2-node returns null."""

    def __init__(self, path: Path) -> None:
        self._reader = geoip2.database.Reader(str(path))

    def __call__(self, ip: str) -> GeoipRecord | None:
        # maxminddb accepts forms geoip2-node rejects: hexadecimal IPv4, IPv6 scope IDs, and IPv6 with a
        # dotted quad unless it is IPv4-mapped. So the address is parsed here first.
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if isinstance(address, ipaddress.IPv6Address) and (
            address.scope_id is not None or ("." in ip and address.ipv4_mapped is None)
        ):
            return None
        try:
            return self._reader.city(address).raw
        except (geoip2.errors.AddressNotFoundError, ValueError):
            return None

    @property
    def build_epoch(self) -> int:
        return self._reader.metadata().build_epoch

    def close(self) -> None:
        self._reader.close()


def geoip_enrichment(
    properties: Mapping[str, Any], lookup: GeoipLookup, version: GeoipTemplateVersion
) -> GeoipEnrichment | None:
    """What the template adds to an event with these properties, or None when it returns the event unchanged."""
    ip = properties.get("$ip")
    if _hog_truthy(properties.get("$geoip_disable")) or not ip or not isinstance(ip, str):
        return None
    if ip == "127.0.0.1" or (version.remaps_private_network and ip[:8] == "192.168."):
        ip = _LOCAL_DEVELOPMENT_IP
    record = lookup(ip)
    if not record:
        return None
    if any(_is_non_object(properties.get(key)) for key in ("$set", "$set_once")):
        # The template's `$set ?? {}` keeps a non-object, and setting a key on it fails the template.
        return None

    location = _location(record)
    set_properties: dict[str, Any] = {f"{GEOIP_PREFIX}{key}": None for key in GEOIP_KEYS}
    set_once_properties: dict[str, Any] = {f"{INITIAL_GEOIP_PREFIX}{key}": None for key in GEOIP_KEYS}
    for key, value in location.items():
        set_properties[f"{GEOIP_PREFIX}{key}"] = value
        set_once_properties[f"{INITIAL_GEOIP_PREFIX}{key}"] = value
    return GeoipEnrichment(
        location={f"{GEOIP_PREFIX}{key}": value for key, value in location.items()},
        set_properties=set_properties,
        set_once_properties=set_once_properties,
    )


def _location(record: GeoipRecord) -> dict[str, Any]:
    # Each `if` mirrors an `if (response.<object>)` of the template, which writes a missing key as null.
    location: dict[str, Any] = {}
    if city := _object_or_empty(record.get("city")):
        location["city_name"] = _english_name(city)
    if country := _object_or_empty(record.get("country")):
        location["country_name"] = _english_name(country)
        location["country_code"] = country.get("iso_code")
    if continent := _object_or_empty(record.get("continent")):
        location["continent_name"] = _english_name(continent)
        location["continent_code"] = continent.get("code")
    if postal := _object_or_empty(record.get("postal")):
        location["postal_code"] = postal.get("code")
    if coordinates := _object_or_empty(record.get("location")):
        location["latitude"] = _js_number(coordinates.get("latitude"))
        location["longitude"] = _js_number(coordinates.get("longitude"))
        location["accuracy_radius"] = _js_number(coordinates.get("accuracy_radius"))
        location["time_zone"] = coordinates.get("time_zone")
    subdivisions = record.get("subdivisions")
    if isinstance(subdivisions, list):
        for index, subdivision in enumerate(subdivisions, start=1):
            subdivision = _object_or_empty(subdivision)
            location[f"subdivision_{index}_code"] = subdivision.get("iso_code")
            location[f"subdivision_{index}_name"] = _english_name(subdivision)
    return location


def _english_name(geo_object: Mapping[str, Any]) -> Any:
    return _object_or_empty(geo_object.get("names")).get("en")


def _js_number(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _hog_truthy(value: Any) -> bool:
    # Hog follows JavaScript, where an empty object or list is true.
    return value is not None and value is not False and value != 0 and value != ""


def _is_non_object(value: Any) -> bool:
    return value is not None and not isinstance(value, Mapping)


def _object_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
