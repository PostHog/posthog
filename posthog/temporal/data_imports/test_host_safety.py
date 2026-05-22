from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.host_safety import _is_host_safe


class TestIsHostSafe(SimpleTestCase):
    @parameterized.expand(
        [
            ("private_10", "10.0.0.1"),
            ("private_172_16", "172.16.0.1"),
            ("private_192_168", "192.168.1.1"),
            ("loopback_127", "127.0.0.1"),
            ("loopback_127_other", "127.0.0.2"),
            ("localhost", "localhost"),
            ("link_local_imds", "169.254.169.254"),
            ("link_local", "169.254.1.1"),
            ("ipv6_mapped_loopback", "::ffff:127.0.0.1"),
            ("ipv6_mapped_imds", "::ffff:169.254.169.254"),
            ("ipv6_mapped_private", "::ffff:10.0.0.1"),
            ("ipv6_loopback", "::1"),
            ("multicast", "224.0.0.1"),
            ("reserved", "0.0.0.0"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_internal_ip(self, _name: str, host: str):
        valid, error = _is_host_safe(host, team_id=999)
        assert not valid
        assert error is not None

    @parameterized.expand(
        [
            ("public_ip", "8.8.8.8"),
            ("public_ip_2", "1.1.1.1"),
            ("public_ip_3", "52.0.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_public_ip(self, _name: str, host: str):
        valid, _ = _is_host_safe(host, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_internal_ip_for_whitelisted_team_us(self):
        valid, _ = _is_host_safe("10.0.0.1", team_id=2)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="EU")
    def test_allows_internal_ip_for_whitelisted_team_eu(self):
        valid, _ = _is_host_safe("10.0.0.1", team_id=1)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_none_team_id_gets_no_allowlist_exemption(self):
        valid, error = _is_host_safe("10.0.0.1", team_id=None)
        assert not valid
        assert error is not None

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolve_false_skips_dns_for_hostnames(self):
        """The cheap pre-flight does no DNS — a hostname passes without resolution."""
        with patch("socket.getaddrinfo") as getaddrinfo:
            valid, error = _is_host_safe("example.com", team_id=999, resolve=False)
        assert valid
        assert error is None
        getaddrinfo.assert_not_called()

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolve_false_still_blocks_literal_internal_ip(self):
        valid, error = _is_host_safe("10.0.0.1", team_id=999, resolve=False)
        assert not valid
        assert error is not None

    @parameterized.expand(
        [
            ("decimal", "2130706433"),  # 127.0.0.1
            ("hex", "0x7f000001"),  # 127.0.0.1
            ("short_form", "127.1"),  # 127.0.0.1
            ("trailing_dot", "127.0.0.1."),
            ("whitespace_padded", "  127.0.0.1  "),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolve_false_blocks_obfuscated_internal_ip(self, _name: str, host: str):
        """The no-DNS pre-flight must not be bypassed by an obfuscated or
        non-canonical (trailing-dot, whitespace-padded) internal IP literal."""
        valid, error = _is_host_safe(host, team_id=999, resolve=False)
        assert not valid
        assert error is not None

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolved_ip_blocks_internal_address(self):
        valid, error = _is_host_safe("api.example.com", team_id=999, resolved_ip="10.0.0.1")
        assert not valid
        assert error is not None

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolved_ip_allows_public_address(self):
        valid, _ = _is_host_safe("api.example.com", team_id=999, resolved_ip="8.8.8.8")
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_resolved_ip_honors_postwh_exemption(self):
        """A .postwh.com host stays allowed even when its peer IP is internal."""
        valid, _ = _is_host_safe("data.postwh.com", team_id=999, resolved_ip="10.0.0.1")
        assert valid

    @parameterized.expand(
        [
            ("localhost", "localhost"),
            ("loopback", "127.0.0.1"),
            ("private_ip", "10.0.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="E2E", E2E_TESTING=True)
    def test_allows_internal_hosts_in_e2e(self, _name: str, host: str):
        valid, error = _is_host_safe(host, team_id=999)
        assert valid
        assert error is None

    @parameterized.expand(
        [
            ("postwh_us", "entirely-chief-wildcat.us.postwh.com"),
            ("postwh_eu", "my-db.eu.postwh.com"),
            ("postwh_bare", "something.postwh.com"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_postwh_hosts(self, _name: str, host: str):
        valid, _ = _is_host_safe(host, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_fake_postwh_suffix(self):
        with patch(
            "posthog.temporal.data_imports.host_safety.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.postwh.com.evil.example.com", team_id=999)
            assert not valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_dns_resolving_to_internal_ip_blocked(self):
        with patch(
            "posthog.temporal.data_imports.host_safety.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.example.com", team_id=999)
            assert not valid
            assert error == "Hosts with internal IP addresses are not allowed"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_dns_resolving_to_public_ip_allowed(self):
        with patch(
            "posthog.temporal.data_imports.host_safety.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("52.1.2.3", 0))],
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_unresolvable_host_blocked(self):
        import socket

        with patch(
            "posthog.temporal.data_imports.host_safety.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            valid, error = _is_host_safe("nonexistent.invalid", team_id=999)
            assert not valid
            assert error == "Host could not be resolved"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocked_host_logs_warning(self):
        with patch("posthog.temporal.data_imports.host_safety.logger") as mock_logger:
            valid, _ = _is_host_safe("10.0.0.1", team_id=999)
            assert not valid
            mock_logger.warning.assert_called_once()
            _args, kwargs = mock_logger.warning.call_args
            assert kwargs["decision"] == "block"
            assert kwargs["stage"] == "literal_ip"
            assert kwargs["host"] == "10.0.0.1"
            mock_logger.info.assert_not_called()

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allowed_resolved_host_logs_info_with_resolved_ips(self):
        with (
            patch(
                "posthog.temporal.data_imports.host_safety.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("52.1.2.3", 0))],
            ),
            patch("posthog.temporal.data_imports.host_safety.logger") as mock_logger,
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid
            mock_logger.info.assert_called_once()
            _args, kwargs = mock_logger.info.call_args
            assert kwargs["decision"] == "allow"
            assert kwargs["stage"] == "resolved_ip"
            assert kwargs["resolved_ips"] == ["52.1.2.3"]
            mock_logger.warning.assert_not_called()
