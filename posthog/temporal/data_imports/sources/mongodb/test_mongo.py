from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from pymongo.server_description import ServerDescription

from posthog.temporal.data_imports.sources.mongodb.mongo import _make_safe_server_selector


class TestSafeServerSelector(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_filters_out_servers_with_internal_ips(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("8.8.8.8", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 1
        assert result[0].address == ("8.8.8.8", 27017)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_returns_empty_when_all_servers_internal(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("192.168.1.1", 27017)),
        ]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_all_public_servers(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("8.8.8.8", 27017)),
            ServerDescription(("1.1.1.1", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 2

    @parameterized.expand(
        [
            ("loopback", "127.0.0.1"),
            ("link_local_imds", "169.254.169.254"),
            ("private_172", "172.16.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_various_internal_addresses(self, _name: str, host: str):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription((host, 27017))]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_whitelisted_team_allows_internal_ips(self):
        selector = _make_safe_server_selector(team_id=2)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1

    @patch("posthog.temporal.data_imports.sources.common.mixins.is_cloud", return_value=False)
    def test_self_hosted_allows_internal_ips(self, _mock_is_cloud):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1
