"""ClickHouse integration, for connecting to a ClickHouse server over its HTTPS interface."""

from typing import Any, ClassVar, Literal

from posthog.models.user import User
from posthog.security.url_validation import (
    INVALID_HOST_MESSAGE,
    UNREACHABLE_HOST_MESSAGE,
    ShapeError,
    validate_external_host,
)

from . import common, model

DEFAULT_CLICKHOUSE_HTTPS_PORT = 8443


class ClickHouseIntegration:
    """Reusable credentials for one user on one ClickHouse server.

    The connection is always HTTPS, the same stance the PostgreSQL integration takes, because
    whatever uses these credentials sends a customer's data across the internet. `verify` only
    turns off certificate verification, which a self-hosted server with a self-signed
    certificate needs. The database stays on whatever uses the integration, so one credential
    serves every database the user can reach.
    """

    integration: model.Integration
    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.CLICKHOUSE]] = (
        model.Integration.IntegrationKind.CLICKHOUSE
    )

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != self.integration_kind:
            raise common.IntegrationError(
                f"Integration provided is not a ClickHouse integration (got kind='{integration.kind}')"
            )
        self.integration = integration

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        created_by: User | None = None,
        **config: Any,
    ) -> model.Integration:
        host = common._return_non_empty_str_from_config(config, "host", friendly_name="Host", kind=cls.integration_kind)
        try:
            validate_external_host(host)
        except ShapeError:
            raise common.IntegrationError(INVALID_HOST_MESSAGE)
        except ValueError:
            raise common.IntegrationError(UNREACHABLE_HOST_MESSAGE)

        try:
            port = int(config.get("port", DEFAULT_CLICKHOUSE_HTTPS_PORT))
        except (TypeError, ValueError):
            raise common.IntegrationError("Port must be an integer")
        if not 0 < port <= 65535:
            raise common.IntegrationError(f"A valid port is required for a {cls.integration_kind} integration")

        user = common._return_non_empty_str_from_config(
            config, "user", friendly_name="A username", kind=cls.integration_kind
        )
        password = common._return_non_empty_str_from_config(
            config, "password", friendly_name="A password", kind=cls.integration_kind
        )

        # A string "false" would read as true, so only a real boolean can turn verification off.
        verify = config.get("verify", True)
        if not isinstance(verify, bool):
            raise common.IntegrationError("Verify must be true or false")

        # Optional, and display only. It stays out of `integration_id` so that two connections to
        # the same server under different names stay one integration.
        name = config.get("name", None)
        if name is not None:
            if not isinstance(name, str):
                raise common.IntegrationError("Name must be a string")
            name = name.strip() or None

        integration_id = f"{team_id}-{host}-{port}-{user}"

        if name is None:
            # `update_or_create` replaces the whole config, so a reconnect that omits the name
            # would otherwise drop the one the user already chose.
            name = (
                model.Integration.objects.filter(
                    team_id=team_id, kind=cls.integration_kind, integration_id=integration_id
                )
                .values_list("config__name", flat=True)
                .first()
            )

        integration, _ = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=cls.integration_kind,
            integration_id=integration_id,
            defaults={
                "config": {
                    "host": host,
                    "port": port,
                    "user": user,
                    "verify": verify,
                    **({"name": name} if name else {}),
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

    @property
    def host(self) -> str:
        return self.integration.config["host"]

    @property
    def port(self) -> int:
        return self.integration.config["port"]

    @property
    def user(self) -> str:
        return self.integration.config["user"]

    @property
    def password(self) -> str:
        return self.integration.sensitive_config["password"]

    @property
    def verify(self) -> bool:
        return self.integration.config.get("verify", True)
