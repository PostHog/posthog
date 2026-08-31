"""Direct-connection PostgreSQL-protocol integrations (Postgres, Redshift over Postgres wire)."""

from typing import ClassVar, Literal, NamedTuple

from posthog.models.user import User

from . import common, model


class Credentials(NamedTuple):
    """PostgreSQL credentials."""

    user: str
    password: str


class Authority(NamedTuple):
    """PostgreSQL authority parameters."""

    host: str
    port: int


MISSING_CERT_PATH = "/tmp/posthog/batch-exports/MISSING.crt"


class TLS(NamedTuple):
    """PostgreSQL TLS parameters.

    NOTE: If a root CA file exists in the default '~/.postgresql/root.crt' path libpq
    treats `sslmode='require'` as `sslmode='verify-ca'`.

    **This is not what we want**

    If a user has not provided a root certificate (by setting `ssl_root_cert` to the
    cert's contents) or asked to use the system store explicitly (by setting
    `ssl_root_cert='system'`, in version >=16), then whatever is present in the default
    path should not be used.

    This could be a problem if, for example, another application or library or
    dependency bundled in the same container ships with a default cert.

    For this reason we require `ssl_root_cert` to not be `None` (as that would translate
    to the default path), and it defaults to an application-scoped path under `/tmp/`.
    """

    ssl_mode: Literal["prefer", "require", "verify-ca", "verify-full"]
    ssl_root_cert: str | Literal["system"] = MISSING_CERT_PATH


_PostgreSQLServerKindType = Literal[
    model.Integration.IntegrationKind.AWS_REDSHIFT, model.Integration.IntegrationKind.POSTGRESQL
]


class PostgreSQLServerIntegration:
    """Base class for any integration targetting a PostgreSQL-server."""

    integration: model.Integration
    integration_kind: ClassVar[_PostgreSQLServerKindType]

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != self.integration_kind:
            raise common.IntegrationError(
                "Integration provided is not the expected PostgreSQL server integration "
                f"(got kind='{integration.kind}', expected kind='{self.integration_kind}')"
            )

        self.integration = integration

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        created_by: User | None = None,
        **config,
    ) -> model.Integration:
        from products.batch_exports.backend.api.batch_export import resolve_and_validate_host

        host = common._return_non_empty_str_from_config(config, "host", friendly_name="Host", kind=cls.integration_kind)
        try:
            resolve_and_validate_host(host)
        except ValueError:
            raise common.IntegrationError(f"Provided host '{host}' is not valid")

        port = config.get("port", None)
        try:
            port = int(port)  # type: ignore
        except (TypeError, ValueError):
            raise common.IntegrationError("Port must be an integer")

        if port > 65535 or port < 0:
            raise common.IntegrationError(f"A valid port is required for an {cls.integration_kind} integration")

        user = common._return_non_empty_str_from_config(
            config,
            "user",
            friendly_name="A username",
            kind=cls.integration_kind,
        )
        password = common._return_non_empty_str_from_config(
            config,
            "password",
            friendly_name="A password",
            kind=cls.integration_kind,
        )

        ssl_mode = config.get("ssl_mode", "require")
        if ssl_mode not in ("require", "verify-ca", "verify-full"):
            raise common.IntegrationError("SSL mode must be one of: require, verify-ca, verify-full")

        ssl_root_cert = config.get("ssl_root_cert", None)
        if ssl_mode in ("verify-ca", "verify-full"):
            if not ssl_root_cert:
                raise common.IntegrationError(
                    "SSL root certificate must be provided when verifying server certificates"
                )
            if not isinstance(ssl_root_cert, str):
                raise common.IntegrationError("SSL root certificate must be a string")

        integration, _ = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=cls.integration_kind,
            integration_id=f"{team_id}-{host}-{port}-{user}",
            defaults={
                "config": {
                    "host": host,
                    "port": port,
                    "user": user,
                    "ssl_mode": ssl_mode,
                    "ssl_root_cert": ssl_root_cert,
                },
                "sensitive_config": {
                    "password": password,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def authority(self) -> Authority:
        return Authority(self.integration.config["host"], self.integration.config["port"])

    def credentials(self) -> Credentials:
        return Credentials(self.integration.config["user"], self.integration.sensitive_config["password"])

    def tls(self) -> TLS:
        if (ssl_root_cert := self.integration.config.get("ssl_root_cert", None)) is not None:
            return TLS(
                ssl_mode=self.integration.config["ssl_mode"],
                ssl_root_cert=ssl_root_cert,
            )
        else:
            # Preserve the default ssl_root_cert if one was not provided
            return TLS(ssl_mode=self.integration.config["ssl_mode"])


class PostgreSQLIntegration(PostgreSQLServerIntegration):
    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.POSTGRESQL]] = (
        model.Integration.IntegrationKind.POSTGRESQL
    )


class RedshiftIntegration(PostgreSQLServerIntegration):
    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.AWS_REDSHIFT]] = (
        model.Integration.IntegrationKind.AWS_REDSHIFT
    )
