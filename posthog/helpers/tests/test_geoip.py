import pytest
from unittest.mock import Mock, patch

from django.contrib.gis.geoip2 import GeoIP2Exception

from geoip2.errors import AddressNotFoundError
from prometheus_client import REGISTRY

from posthog.geoip import get_geoip_properties

australia_ip = "13.106.122.3"
uk_ip = "31.28.64.3"
us_ip_v6 = "2600:6c52:7a00:11c:1b6:b7b0:ea19:6365"
mexico_ip = "187.188.10.252"


@pytest.mark.parametrize(
    "test_input,expected_country",
    [
        (australia_ip, "Australia"),
        (uk_ip, "United Kingdom"),
        (us_ip_v6, "United States"),
        (mexico_ip, "Mexico"),
        (australia_ip, "Australia"),
    ],
)
def test_geoip_results(test_input, expected_country):
    properties = get_geoip_properties(test_input)
    assert properties["$geoip_country_name"] == expected_country
    # GeoIP databases may have varying levels of detail for different IPs
    # Minimum properties: country_code, country_name, continent_code, continent_name, time_zone
    # Optional properties: city_name, city_confidence (depend on database version/coverage)
    assert len(properties) >= 5


def _failure_count(reason: str) -> float:
    return REGISTRY.get_sample_value("geoip_lookup_failures_total", {"reason": reason}) or 0.0


def _total_failure_count() -> float:
    return sum(
        sample.value
        for metric in REGISTRY.collect()
        if metric.name == "geoip_lookup_failures"
        for sample in metric.samples
        if sample.name == "geoip_lookup_failures_total"
    )


@pytest.mark.parametrize(
    "non_public_ip",
    [
        pytest.param("127.0.0.1", id="ipv4_loopback"),
        pytest.param("::1", id="ipv6_loopback"),
        pytest.param("10.0.0.42", id="rfc1918_10"),
        pytest.param("172.20.0.42", id="rfc1918_172"),
        pytest.param("192.168.0.42", id="rfc1918_192"),
        pytest.param("169.254.42.42", id="link_local"),
        pytest.param("240.0.0.42", id="reserved"),
        pytest.param("0.0.0.0", id="unspecified"),
        pytest.param("100.64.0.42", id="rfc6598_shared"),
        pytest.param("224.0.0.42", id="multicast"),
        pytest.param("fec0::42", id="ipv6_site_local"),
    ],
)
def test_geoip_skips_non_public_addresses_without_a_lookup(non_public_ip: str) -> None:
    before = _total_failure_count()
    with patch("posthog.geoip.geoip") as mock_geoip:
        assert get_geoip_properties(non_public_ip) == {}
    mock_geoip.city.assert_not_called()
    assert _total_failure_count() == before


def test_geoip_on_invalid_ip_counts_an_invalid_failure() -> None:
    with patch("posthog.geoip.geoip"):
        before = _failure_count("invalid")
        assert get_geoip_properties("not-an-ip-address") == {}
    assert _failure_count("invalid") == before + 1


@pytest.mark.parametrize(
    "reason,exc",
    [
        ("lookup_error", GeoIP2Exception("GeoIP file not found")),
        ("not_found", AddressNotFoundError("The address is not in the database.")),
    ],
)
def test_failed_public_lookup_returns_empty_and_counts_reason(reason: str, exc: Exception) -> None:
    mock_geoip = Mock()
    mock_geoip.city.side_effect = exc
    with patch("posthog.geoip.geoip", mock_geoip):
        before = _failure_count(reason)
        assert get_geoip_properties("8.8.8.8") == {}
    assert _failure_count(reason) == before + 1


def test_geoip_on_missing_ip_returns_successfully() -> None:
    assert get_geoip_properties(None) == {}
