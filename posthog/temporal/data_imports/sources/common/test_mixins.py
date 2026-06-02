import asyncio
from dataclasses import dataclass

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.mixins import (
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
    _is_host_safe,
    aopen_ssh_tunnel_for_config,
    ssh_tunnel_config_is_valid,
    ssh_tunnel_requires_tls,
)


def _ssh_tunnel_config(**overrides) -> dict:
    config = {
        "enabled": True,
        "host": "8.8.8.8",
        "port": 22,
        "auth": {"selection": "password", "username": "user", "password": "pw"},
        "require_tls": {"enabled": True},
    }
    config.update(overrides)
    return config


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
            "posthog.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.postwh.com.evil.example.com", team_id=999)
            assert not valid

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

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocked_host_logs_warning(self):
        with patch("posthog.temporal.data_imports.sources.common.mixins.logger") as mock_logger:
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
                "posthog.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("52.1.2.3", 0))],
            ),
            patch("posthog.temporal.data_imports.sources.common.mixins.logger") as mock_logger,
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid
            mock_logger.info.assert_called_once()
            _args, kwargs = mock_logger.info.call_args
            assert kwargs["decision"] == "allow"
            assert kwargs["stage"] == "resolved_ip"
            assert kwargs["resolved_ips"] == ["52.1.2.3"]
            mock_logger.warning.assert_not_called()


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


class TestSSHTunnelConfigIsValid(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_valid_password_config(self):
        valid, error = ssh_tunnel_config_is_valid(_ssh_tunnel_config(), team_id=999)
        assert valid
        assert error is None

    def test_none_config_is_valid(self):
        valid, error = ssh_tunnel_config_is_valid(None, team_id=999)
        assert valid
        assert error is None

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_disabled_config_skips_validation(self):
        valid, _ = ssh_tunnel_config_is_valid(_ssh_tunnel_config(enabled=False, host="10.0.0.1"), team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_internal_host_blocked(self):
        valid, error = ssh_tunnel_config_is_valid(_ssh_tunnel_config(host="10.0.0.1"), team_id=999)
        assert not valid
        assert "SSH tunnel host not allowed" in error  # type: ignore

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_missing_host_blocked(self):
        valid, error = ssh_tunnel_config_is_valid(_ssh_tunnel_config(host=None), team_id=999)
        assert not valid
        assert "host is required" in error.lower()  # type: ignore

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_invalid_auth_blocked(self):
        valid, error = ssh_tunnel_config_is_valid(
            _ssh_tunnel_config(auth={"selection": "password", "username": "user"}), team_id=999
        )
        assert not valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_disallowed_port_blocked(self):
        valid, error = ssh_tunnel_config_is_valid(_ssh_tunnel_config(port=443), team_id=999)
        assert not valid


class TestSSHTunnelRequiresTLS(SimpleTestCase):
    def test_no_config_requires_tls(self):
        assert ssh_tunnel_requires_tls(None) is True

    def test_enabled_with_tls_requires_tls(self):
        assert ssh_tunnel_requires_tls(_ssh_tunnel_config(require_tls={"enabled": True})) is True

    def test_enabled_without_tls_does_not_require_tls(self):
        assert ssh_tunnel_requires_tls(_ssh_tunnel_config(require_tls={"enabled": False})) is False

    def test_disabled_tunnel_requires_tls(self):
        assert ssh_tunnel_requires_tls(_ssh_tunnel_config(enabled=False, require_tls={"enabled": False})) is True


class TestAOpenSSHTunnelForConfig(SimpleTestCase):
    def test_no_config_yields_original_host(self):
        async def run() -> tuple[str, int]:
            async with aopen_ssh_tunnel_for_config(None, "db.example.com", 5432) as (host, port):
                return host, port

        assert asyncio.run(run()) == ("db.example.com", 5432)

    def test_disabled_config_yields_original_host(self):
        async def run() -> tuple[str, int]:
            async with aopen_ssh_tunnel_for_config(_ssh_tunnel_config(enabled=False), "db.example.com", 5432) as (
                host,
                port,
            ):
                return host, port

        assert asyncio.run(run()) == ("db.example.com", 5432)

    def test_enabled_config_yields_local_bind_address(self):
        forwarder = MagicMock()
        forwarder.local_bind_host = "127.0.0.1"
        forwarder.local_bind_port = 54321
        tunnel = MagicMock()
        tunnel.get_tunnel.return_value = forwarder

        async def run() -> tuple[str, int]:
            async with aopen_ssh_tunnel_for_config(_ssh_tunnel_config(), "db.example.com", 5432) as (host, port):
                return host, port

        with patch(
            "posthog.temporal.data_imports.sources.common.mixins.SSHTunnel.from_config",
            return_value=tunnel,
        ):
            result = asyncio.run(run())

        assert result == ("127.0.0.1", 54321)
        tunnel.get_tunnel.assert_called_once_with("db.example.com", 5432)
        forwarder.start.assert_called_once()
        forwarder.stop.assert_called_once()
