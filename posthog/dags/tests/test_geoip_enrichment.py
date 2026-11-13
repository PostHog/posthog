import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import brotli

from posthog.dags.geoip_enrichment import (
    GEOIP_KEYS,
    TEMPLATE_VERSIONS,
    MmdbGeoipLookup,
    geoip_enrichment,
    template_version,
)

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT_VERSION = TEMPLATE_VERSIONS[-1]

# Recorded from the Node template, one file per shipped version. To add a case, run the template through
# TemplateTester (it loads the same test DB, from nodejs/tests/assets) and copy the event properties it
# returns.
PARITY_FIXTURES = [json.loads(path.read_text()) for path in sorted(FIXTURES.glob("geoip_template_parity*.json"))]
PARITY_CASES = [
    pytest.param(fixture["source_sha256"], case, id=f"{fixture['source_sha256'][:8]}-{case['name']}")
    for fixture in PARITY_FIXTURES
    for case in fixture["cases"]
]

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


def test_template_version_matches_the_saved_source_of_the_current_template() -> None:
    template = (
        Path(__file__).parents[3] / "nodejs/src/cdp/templates/_transformations/geoip/geoip.template.ts"
    ).read_text()
    hog = template.split("code: `", 1)[1].split("`,", 1)[0]

    assert template_version(f"\n  {hog}\n\t") == CURRENT_VERSION
    assert template_version(f"{hog}\n// edited") is None


def test_every_shipped_template_version_has_a_parity_fixture() -> None:
    assert sorted(fixture["source_sha256"] for fixture in PARITY_FIXTURES) == sorted(
        version.source_sha256 for version in TEMPLATE_VERSIONS
    )


@pytest.mark.parametrize("source_sha256, case", PARITY_CASES)
def test_geoip_enrichment_matches_the_node_template(
    source_sha256: str, case: dict[str, Any], test_db_lookup: MmdbGeoipLookup
) -> None:
    [version] = [version for version in TEMPLATE_VERSIONS if version.source_sha256 == source_sha256]
    properties = case["properties"]
    enrichment = geoip_enrichment(properties, test_db_lookup, version)
    enriched = properties if enrichment is None else enrichment.apply(properties)
    assert enriched == case["expected"]
    # The text also has to match: `13.0 == 13` holds in Python, but the stored JSON would read 13.0.
    assert json.dumps(enriched) == json.dumps(case["expected"])


def test_geoip_enrichment_writes_null_for_objects_without_english_names() -> None:
    record = {
        **MILTON_RECORD,
        "city": {"geoname_id": 1},
        "subdivisions": [{"iso_code": "ENG", "names": {"en": "England"}}, {"iso_code": "WSM"}],
    }
    enrichment = geoip_enrichment({"$ip": "216.160.83.56"}, lambda ip: record, CURRENT_VERSION)

    assert enrichment is not None
    assert enrichment.location["$geoip_city_name"] is None
    assert enrichment.location["$geoip_subdivision_1_name"] == "England"
    assert enrichment.location["$geoip_subdivision_2_code"] == "WSM"
    assert enrichment.location["$geoip_subdivision_2_name"] is None
    assert set(enrichment.set_properties) == {f"$geoip_{key}" for key in GEOIP_KEYS}
