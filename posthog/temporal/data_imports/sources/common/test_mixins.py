from dataclasses import dataclass

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin, _is_host_safe


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
    def test_dns_resolving_to_internal_ip_blocked(self):
        with patch(
            "posthog.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.example.com", team_id=999)
            assert not valid
            assert error == "Hosts with internal IP addresses are not allowed"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_dns_resolving_to_public_ip_allowed(self):
        with patch(
            "posthog.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("52.1.2.3", 0))],
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_unresolvable_host_blocked(self):
        import socket

        with patch(
            "posthog.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            valid, error = _is_host_safe("nonexistent.invalid", team_id=999)
            assert not valid
            assert error == "Host could not be resolved"


class TestValidateDatabaseHostMixin(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_private_ip(self):
        mixin = ValidateDatabaseHostMixin()
        valid, error = mixin.is_database_host_valid("192.168.1.1", team_id=999)
        assert not valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_public_ip(self):
        mixin = ValidateDatabaseHostMixin()
        valid, _ = mixin.is_database_host_valid("8.8.8.8", team_id=999)
        assert valid


@dataclass
class FakeSSHTunnelConfig:
    enabled: bool
    host: str
    port: int = 22


@dataclass
class FakeConfig:
    host: str = "dbhost.example.com"
    port: int = 5432
    ssh_tunnel: FakeSSHTunnelConfig | None = None


class TestSSHTunnelHostValidation(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_with_internal_host_blocked(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=True, host="10.0.0.1"))
        valid, error = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert not valid
        assert "SSH tunnel host not allowed" in error  # type: ignore

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_disabled_skips_validation(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=False, host="10.0.0.1"))
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_no_ssh_tunnel_skips_validation(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=None)
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert valid

    @parameterized.expand(
        [
            ("imds", "169.254.169.254"),
            ("loopback", "127.0.0.1"),
            ("private_192", "192.168.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_blocks_various_internal_hosts(self, _name: str, host: str):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=True, host=host))
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert not valid
