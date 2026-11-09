from typing import Any

import pytest

from posthog.dags.geoip_enrichment import GEOIP_KEYS, geoip_enrichment

# The raw MaxMind record of 216.160.83.56 in the GeoIP2 test database, which geoip.template.test.ts enriches.
MILTON_RECORD: dict[str, Any] = {
    "city": {"geoname_id": 5803556, "names": {"en": "Milton", "de": "Milton"}},
    "continent": {"code": "NA", "geoname_id": 6255149, "names": {"en": "North America"}},
    "country": {"geoname_id": 6252001, "iso_code": "US", "names": {"en": "United States"}},
    "location": {
        "accuracy_radius": 22,
        "latitude": 47.2513,
        "longitude": -122.3149,
        "time_zone": "America/Los_Angeles",
    },
    "postal": {"code": "98354"},
    "registered_country": {"geoname_id": 2635167, "iso_code": "GB", "names": {"en": "United Kingdom"}},
    "subdivisions": [{"geoname_id": 5815135, "iso_code": "WA", "names": {"en": "Washington"}}],
}

# The event properties geoip.template.test.ts expects for MILTON_RECORD, without `$ip`, `$set` and `$set_once`.
MILTON_LOCATION: dict[str, Any] = {
    "$geoip_accuracy_radius": 22,
    "$geoip_city_name": "Milton",
    "$geoip_continent_code": "NA",
    "$geoip_continent_name": "North America",
    "$geoip_country_code": "US",
    "$geoip_country_name": "United States",
    "$geoip_latitude": 47.2513,
    "$geoip_longitude": -122.3149,
    "$geoip_postal_code": "98354",
    "$geoip_subdivision_1_code": "WA",
    "$geoip_subdivision_1_name": "Washington",
    "$geoip_time_zone": "America/Los_Angeles",
}


def all_keys(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}{key}": values.get(f"$geoip_{key}") for key in GEOIP_KEYS}


@pytest.mark.parametrize(
    "properties, record, expected_lookup_ip, expected_location",
    [
        pytest.param({"$ip": "216.160.83.56"}, MILTON_RECORD, "216.160.83.56", MILTON_LOCATION, id="full_record"),
        pytest.param(
            {"$ip": "216.160.83.56"},
            {key: value for key, value in MILTON_RECORD.items() if key != "city"},
            "216.160.83.56",
            {key: value for key, value in MILTON_LOCATION.items() if key != "$geoip_city_name"},
            id="record_without_city",
        ),
        pytest.param(
            {"$ip": "216.160.83.56"},
            {
                **MILTON_RECORD,
                "city": {"geoname_id": 1},
                "subdivisions": [{"iso_code": "ENG", "names": {"en": "England"}}, {"iso_code": "WSM"}],
            },
            "216.160.83.56",
            {
                **MILTON_LOCATION,
                "$geoip_city_name": None,
                "$geoip_subdivision_1_code": "ENG",
                "$geoip_subdivision_1_name": "England",
                "$geoip_subdivision_2_code": "WSM",
                "$geoip_subdivision_2_name": None,
            },
            id="objects_without_english_names",
        ),
        pytest.param({"$ip": "192.168.1.10"}, MILTON_RECORD, "89.160.20.129", MILTON_LOCATION, id="local_ip_spoof"),
    ],
)
def test_geoip_enrichment_matches_the_template(
    properties: dict[str, Any],
    record: dict[str, Any],
    expected_lookup_ip: str,
    expected_location: dict[str, Any],
) -> None:
    looked_up: list[str] = []

    def lookup(ip: str) -> dict[str, Any]:
        looked_up.append(ip)
        return record

    existing = {**properties, "$set": {"email": "user@example.com"}, "$set_once": {"$initial_os": "Mac OS X"}}
    enrichment = geoip_enrichment(existing, lookup)

    assert looked_up == [expected_lookup_ip]
    assert enrichment is not None
    assert enrichment.apply(existing) == {
        **properties,
        **expected_location,
        "$set": {"email": "user@example.com", **all_keys("$geoip_", expected_location)},
        "$set_once": {"$initial_os": "Mac OS X", **all_keys("$initial_geoip_", expected_location)},
    }


@pytest.mark.parametrize(
    "properties, record",
    [
        pytest.param({"$ip": "216.160.83.56", "$geoip_disable": True}, MILTON_RECORD, id="geoip_disabled"),
        pytest.param({}, MILTON_RECORD, id="no_ip"),
        pytest.param({"$ip": ""}, MILTON_RECORD, id="empty_ip"),
        pytest.param({"$ip": "216.160.83.56"}, None, id="no_record"),
        pytest.param({"$ip": "216.160.83.56"}, {}, id="empty_record"),
    ],
)
def test_geoip_enrichment_leaves_the_event_unchanged(properties: dict[str, Any], record: dict[str, Any] | None) -> None:
    assert geoip_enrichment(properties, lambda ip: record) is None
