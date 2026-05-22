from dataclasses import dataclass

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin

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
