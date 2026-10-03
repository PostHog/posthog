"""Tests for direct-connection PostgreSQL-protocol integrations."""

from posthog.test.base import BaseTest

from parameterized import parameterized, parameterized_class

from posthog.models.integration import (
    MISSING_CERT_PATH,
    TLS,
    Authority,
    Credentials,
    Integration,
    PostgreSQLIntegration,
    RedshiftIntegration,
)


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
