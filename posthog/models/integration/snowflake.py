"""Snowflake integration."""

import re

from django.db import transaction

from posthog.models.user import User
from posthog.models.utils import IntegrityError

from . import model


class SnowflakeIntegrationError(Exception):
    """Error raised when a Snowflake integration is not valid."""

    pass


# A Snowflake account identifier: an alphanumeric first character followed by alphanumerics, dots,
# hyphens and underscores.
_SNOWFLAKE_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SnowflakeIntegration:
    """A Snowflake integration storing reusable Snowflake credentials.

    Holds the account, user, and authentication material (a password, or a key-pair) needed to
    connect to Snowflake. Database, warehouse, schema, table name and role stay on the batch export
    destination config, so one credential can be reused across many exports.

    Supports both of Snowflake's authentication types:
      - "password": `password` in sensitive_config.
      - "keypair": `private_key` (PEM) plus optional `private_key_passphrase` in sensitive_config.

    Rather than using an auto-generated ID (e.g. '{account}-{user}-{auth_type}'), we use a
    user-provided name, similarly to how we do for S3 integrations. The benefits of this approach
    are:
        - a user can create multiple integrations for the same account, allowing for credential rotation
        - we don't overwrite an existing integration if creating an integration for the same account,
          so existing exports can continue to use the old credentials
        - a human-readable name in the UI
    """

    integration: model.Integration
    account: str
    user: str
    authentication_type: str

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != model.Integration.IntegrationKind.SNOWFLAKE:
            raise SnowflakeIntegrationError(
                f"Integration provided is not a Snowflake integration (got kind='{integration.kind}')"
            )
        self.integration = integration
        try:
            self.account = integration.config["account"]
            self.user = integration.config["user"]
            self.authentication_type = integration.config["authentication_type"]
        except KeyError as e:
            raise SnowflakeIntegrationError(f"Snowflake integration is not valid: {str(e)} missing")

    @property
    def password(self) -> str | None:
        return self.integration.sensitive_config.get("password")

    @property
    def private_key(self) -> str | None:
        return self.integration.sensitive_config.get("private_key")

    @property
    def private_key_passphrase(self) -> str | None:
        return self.integration.sensitive_config.get("private_key_passphrase")

    @staticmethod
    def validate_account(account: str) -> None:
        """Validate the Snowflake account identifier format.

        Snowflake has no user-supplied host: the connector derives the host from the account, always
        on a fixed Snowflake-owned domain suffix, so there is no SSRF surface as there is for
        Databricks or S3-compatible. We validate the identifier's shape to reject URLs and arbitrary
        hosts (for example, anything with a scheme, `/`, `@`, `:`, `#`, or whitespace).
        """
        if not _SNOWFLAKE_ACCOUNT_RE.fullmatch(account):
            raise SnowflakeIntegrationError(
                f"Snowflake integration is not valid: invalid account identifier '{account}'"
            )

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        name: str,
        account: str,
        user: str,
        authentication_type: str,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        created_by: User | None = None,
    ) -> model.Integration:
        if not (name and account and user):
            raise SnowflakeIntegrationError("Name, account, and user must be provided")
        if not all(isinstance(value, str) for value in (name, account, user, authentication_type)):
            raise SnowflakeIntegrationError("Name, account, user, and authentication type must be strings")
        if not all(
            value is None or isinstance(value, str) for value in (password, private_key, private_key_passphrase)
        ):
            raise SnowflakeIntegrationError("Password, private key, and private key passphrase must be strings")

        cls.validate_account(account)

        sensitive_config: dict[str, str] = {}
        if authentication_type == "password":
            if not password:
                raise SnowflakeIntegrationError("Password is required for password authentication")
            sensitive_config["password"] = password
        elif authentication_type == "keypair":
            if not private_key:
                raise SnowflakeIntegrationError("Private key is required for key-pair authentication")
            sensitive_config["private_key"] = private_key
            if private_key_passphrase:
                sensitive_config["private_key_passphrase"] = private_key_passphrase
        else:
            raise SnowflakeIntegrationError(f"Invalid authentication type: {authentication_type}")

        # `name` is the unencrypted, frontend-visible identifier — never a credential. Unlike most
        # integrations, it is a free-form user-supplied name rather than one derived from the
        # connection, so we create rather than upsert: re-using a name is a 400, not a silent
        # overwrite of an unrelated credential set.
        try:
            # Savepoint so the unique-constraint IntegrityError aborts only this INSERT, not the
            # surrounding transaction.
            with transaction.atomic():
                return model.Integration.objects.create(
                    team_id=team_id,
                    kind=model.Integration.IntegrationKind.SNOWFLAKE,
                    integration_id=name,
                    config={
                        "name": name,
                        "account": account,
                        "user": user,
                        "authentication_type": authentication_type,
                    },
                    sensitive_config=sensitive_config,
                    created_by=created_by,
                )
        except IntegrityError:
            raise SnowflakeIntegrationError(f"An integration named '{name}' already exists")
