import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import brotli

from posthog.dags.geoip_enrichment import GEOIP_KEYS, MmdbGeoipLookup, geoip_enrichment

FIXTURES = Path(__file__).parent / "fixtures"

# Recorded from the Node template. To add a case, run the template through TemplateTester (it loads the
# same test DB, from nodejs/tests/assets) and copy the event properties it returns.
PARITY_CASES: list[dict[str, Any]] = json.loads((FIXTURES / "geoip_template_parity.json").read_text())["cases"]

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


@pytest.fixture(scope="module")
def test_db_lookup(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MmdbGeoipLookup]:
    path = tmp_path_factory.mktemp("mmdb") / "GeoLite2-City-Test.mmdb"
    path.write_bytes(brotli.decompress((FIXTURES / "GeoLite2-City-Test.mmdb.br").read_bytes()))
    lookup = MmdbGeoipLookup(path)
    yield lookup
    lookup.close()


@pytest.mark.parametrize("case", PARITY_CASES, ids=[case["name"] for case in PARITY_CASES])
def test_geoip_enrichment_matches_the_node_template(case: dict[str, Any], test_db_lookup: MmdbGeoipLookup) -> None:
    properties = case["properties"]
    enrichment = geoip_enrichment(properties, test_db_lookup)
    assert (properties if enrichment is None else enrichment.apply(properties)) == case["expected"]


def test_geoip_enrichment_writes_null_for_objects_without_english_names() -> None:
    record = {
        **MILTON_RECORD,
        "city": {"geoname_id": 1},
        "subdivisions": [{"iso_code": "ENG", "names": {"en": "England"}}, {"iso_code": "WSM"}],
    }
    enrichment = geoip_enrichment({"$ip": "216.160.83.56"}, lambda ip: record)

    assert enrichment is not None
    assert enrichment.location["$geoip_city_name"] is None
    assert enrichment.location["$geoip_subdivision_1_name"] == "England"
    assert enrichment.location["$geoip_subdivision_2_code"] == "WSM"
    assert enrichment.location["$geoip_subdivision_2_name"] is None
    assert set(enrichment.set_properties) == {f"$geoip_{key}" for key in GEOIP_KEYS}
