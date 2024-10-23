from typing import cast
from unittest.mock import Mock

import pytest
from django.contrib.gis.geoip2 import GeoIP2, GeoIP2Exception
from django.test import TestCase

from posthog.geoip import geoip, get_geoip_properties

australia_ip = "13.106.122.3"
uk_ip = "31.28.64.3"
us_ip_v6 = "2600:6c52:7a00:11c:1b6:b7b0:ea19:6365"
local_ip = "127.0.0.1"
mexico_ip = "187.188.10.252"
australia_ip_2 = "13.106.122.3"


@pytest.mark.parametrize(
    "test_input,expected_country,expected_city",
    [
        (australia_ip, "Australia", "Sydney"),
        (uk_ip, "United Kingdom", "Royston"),
        (us_ip_v6, "United States", "San Luis Obispo"),
        (mexico_ip, "Mexico", "Cuauhtémoc"),
        (australia_ip, "Australia", "Sydney"),
    ],
)
def test_geoip_results(test_input, expected_country, expected_city):
    properties = get_geoip_properties(test_input)
    assert properties["$geoip_country_name"] == expected_country
    assert properties["$geoip_city_name"] == expected_city
    assert len(properties) == 7


class TestGeoIPDBError(TestCase):
    def setUp(self) -> None:
        self.geoip_city_method = cast(GeoIP2, geoip).city
        geoip.city = Mock(side_effect=GeoIP2Exception("GeoIP file not found"))  # type: ignore

    def tearDown(self) -> None:
        geoip.city = self.geoip_city_method  # type: ignore

    def test_geoip_with_invalid_database_file_returns_successfully(self):
        properties = get_geoip_properties(australia_ip)

        self.assertEqual(properties, {})


class TestGeoIPError(TestCase):
    def test_geoip_on_local_ip_returns_successfully(self):
        properties = get_geoip_properties(local_ip)

        self.assertEqual(properties, {})

    def test_geoip_on_invalid_ip_returns_successfully(self):
        properties = get_geoip_properties(None)

        self.assertEqual(properties, {})
