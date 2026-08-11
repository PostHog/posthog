from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.geoip import _lookup_location, get_geoip_location


class TestGeoipLocation(BaseTest):
    def setUp(self):
        super().setUp()
        # Lookups are memoized per process, so results would otherwise leak across tests that mock
        # different responses for the same address.
        _lookup_location.cache_clear()

    def test_returns_empty_for_local_ip(self):
        self.assertEqual(get_geoip_location("127.0.0.1"), {})

    @parameterized.expand(
        [
            ("rfc1918_10", "10.0.0.5"),
            ("rfc1918_172", "172.16.3.4"),
            ("rfc1918_192", "192.168.1.1"),
            ("ipv6_loopback", "::1"),
            ("link_local", "169.254.0.1"),
        ]
    )
    @patch("posthog.geoip.geoip")
    def test_returns_empty_for_non_public_ip(self, _name, ip, mock_geoip):
        # geoip is mocked truthy, so an empty result can only come from the private/reserved guard,
        # not a missing DB — and city() must never be reached for these ranges.
        self.assertEqual(get_geoip_location(ip), {})
        mock_geoip.city.assert_not_called()

    @patch("posthog.geoip.geoip")
    def test_returns_coordinates_and_country(self, mock_geoip):
        mock_geoip.city.return_value = {"latitude": 40.7, "longitude": -74.0, "country_code": "US", "city": "NYC"}
        result = get_geoip_location("8.8.8.8")
        self.assertEqual(result, {"latitude": 40.7, "longitude": -74.0, "country_code": "US"})

    @patch("posthog.geoip.geoip")
    def test_repeat_lookups_hit_the_database_once(self, mock_geoip):
        # This runs on every authenticated request and a lookup costs ~75us, so a repeated address
        # must not reach the database again.
        mock_geoip.city.return_value = {"latitude": 40.7, "longitude": -74.0, "country_code": "US"}

        for _ in range(3):
            get_geoip_location("8.8.8.8")

        mock_geoip.city.assert_called_once()

    @patch("posthog.geoip.geoip")
    def test_callers_cannot_corrupt_a_cached_entry(self, mock_geoip):
        # Callers own the dict they get back; mutating it must not reach the next caller.
        mock_geoip.city.return_value = {"latitude": 40.7, "longitude": -74.0, "country_code": "US"}

        first = get_geoip_location("8.8.8.8")
        first["country_code"] = "XX"
        first["latitude"] = 0.0

        self.assertEqual(get_geoip_location("8.8.8.8"), {"latitude": 40.7, "longitude": -74.0, "country_code": "US"})
