"""Tests for direct-connection PostgreSQL-protocol integrations."""

import ipaddress

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized, parameterized_class

from posthog.models.integration import (
    MISSING_CERT_PATH,
    TLS,
    Authority,
    Credentials,
    Integration,
    IntegrationError,
    PostgreSQLIntegration,
    RedshiftIntegration,
)
from posthog.security.postgres_hosts import IPV6_ONLY_HOST_MESSAGE, SUPABASE_DIRECT_HOST_DESTINATION_HINT

IPV4 = ipaddress.ip_address("203.0.113.10")
IPV6 = ipaddress.ip_address("2001:db8::10")


@parameterized_class(
    [
        {
            "integration_cls": PostgreSQLIntegration,
            "integration_kind": Integration.IntegrationKind.POSTGRESQL,
        },
        {
            "integration_cls": RedshiftIntegration,
            "integration_kind": Integration.IntegrationKind.AWS_REDSHIFT,
        },
    ]
)
class TestPostgreSQLIntegrationModel(BaseTest):
    integration_kind: Integration.IntegrationKind
    integration_cls: type[RedshiftIntegration] | type[PostgreSQLIntegration]

    @parameterized.expand(
        [
            (
                "require_no_cert",
                {"ssl_mode": "require"},
                {},
                TLS(ssl_mode="require", ssl_root_cert=MISSING_CERT_PATH),
            ),
            (
                "require_system_cert",
                {"ssl_mode": "require", "ssl_root_cert": "system"},
                {},
                TLS(ssl_mode="require", ssl_root_cert="system"),
            ),
            (
                "verify_ca_with_cert",
                {
                    "ssl_mode": "verify-ca",
                    "ssl_root_cert": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
                },
                {},
                TLS(
                    ssl_mode="verify-ca",
                    ssl_root_cert="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
                ),
            ),
            (
                "prefer_no_cert",
                {"ssl_mode": "prefer"},
                {},
                TLS(ssl_mode="prefer", ssl_root_cert=MISSING_CERT_PATH),
            ),
        ]
    )
    def test_tls_with_ssl_configs(self, _name, config_overrides, sensitive_config_overrides, expected_tls):
        config = {"host": "db.example.com", "port": 5432, "user": "exporter"}
        config.update(config_overrides)

        sensitive_config: dict = {"password": "hunter2"}
        sensitive_config.update(sensitive_config_overrides)

        integration = Integration.objects.create(
            team=self.team,
            kind=self.integration_kind,
            integration_id=f"{self.team.pk}-db.example.com-5432-exporter",
            config=config,
            sensitive_config=sensitive_config,
        )

        pq = self.integration_cls(integration)
        assert pq.tls() == expected_tls

    @parameterized.expand(
        [
            (
                "defaults",
                {},
                TLS(ssl_mode="require", ssl_root_cert=MISSING_CERT_PATH),
            ),
            (
                "system_cert",
                {"ssl_root_cert": "system"},
                TLS(ssl_mode="require", ssl_root_cert="system"),
            ),
            (
                "verify_full_with_cert",
                {"ssl_mode": "verify-full", "ssl_root_cert": "cert-data"},
                TLS(ssl_mode="verify-full", ssl_root_cert="cert-data"),
            ),
        ]
    )
    def test_integration_from_config(self, _name, overrides, expected_tls):
        kwargs = {
            "team_id": self.team.pk,
            "host": "localhost",
            "port": 5432,
            "user": "exporter",
            "password": "super-secret",
        }
        kwargs.update(overrides)

        integration = self.integration_cls.integration_from_config(**kwargs)  # type: ignore
        pq = self.integration_cls(integration)

        assert pq.authority() == Authority(host="localhost", port=5432)
        assert pq.credentials() == Credentials(user="exporter", password="super-secret")
        assert pq.tls() == expected_tls

        assert "password" not in integration.config

        assert integration.sensitive_config["password"] == "super-secret"
        assert pq.integration_kind == self.integration_kind

    @parameterized.expand(
        [
            ("ipv6_only_no_route", "db.example.com", {IPV6}, False, IPV6_ONLY_HOST_MESSAGE),
            (
                "several_ipv6_no_route",
                "db.example.com",
                {IPV6, ipaddress.ip_address("2001:db8::11")},
                False,
                IPV6_ONLY_HOST_MESSAGE,
            ),
            ("ipv6_only_with_route", "db.example.com", {IPV6}, True, None),
            ("dual_stack_no_route", "db.example.com", {IPV4, IPV6}, False, None),
            ("ipv4_only_no_route", "db.example.com", {IPV4}, False, None),
            ("unresolved_is_left_to_host_validation", "db.example.com", set(), False, None),
            (
                "supabase_direct_host_gets_pooler_hint",
                "db.abcdefghijklmnop.supabase.co",
                {IPV6},
                False,
                SUPABASE_DIRECT_HOST_DESTINATION_HINT,
            ),
            ("supabase_direct_host_with_ipv4_add_on", "db.abcdefghijklmnop.supabase.co", {IPV4}, False, None),
        ]
    )
    def test_integration_from_config_rejects_ipv6_only_hosts(self, _name, host, resolved, has_route, expected_error):
        kwargs = {"team_id": self.team.pk, "host": host, "port": 5432, "user": "exporter", "password": "pw"}

        with (
            patch("posthog.models.integration.postgres.validate_external_host"),
            patch("posthog.models.integration.postgres.resolve_host_ips", return_value=resolved),
            patch("posthog.models.integration.postgres.has_ipv6_route", return_value=has_route),
        ):
            if expected_error is None:
                integration = self.integration_cls.integration_from_config(**kwargs)
                assert integration.config["host"] == host
            else:
                with self.assertRaises(IntegrationError) as raised:
                    self.integration_cls.integration_from_config(**kwargs)
                assert str(raised.exception) == expected_error
