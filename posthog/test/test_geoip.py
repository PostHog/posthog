from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.geoip import get_geoip_location


class TestGeoipLocation(BaseTest):
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
