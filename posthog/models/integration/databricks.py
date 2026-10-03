"""Databricks integration."""

from posthog.models.user import User
from posthog.security.url_validation import is_url_allowed

from . import model


class DatabricksIntegrationError(Exception):
    """Error raised when the Databricks integration is not valid."""

    pass


class DatabricksIntegration:
    """A Databricks integration.

    The recommended way to connect to Databricks is via OAuth machine-to-machine (M2M) authentication.
    See: https://docs.databricks.com/aws/en/dev-tools/python-sql-connector#oauth-machine-to-machine-m2m-authentication

    This works quite differently to regular user-to-machine OAuth as it does not require a real-time user sign in and
    consent flow: Instead, the user creates a service principal and provided us with the client ID and client secret to authenticate.

    Attributes:
        integration: The integration object.
        server_hostname: the Server Hostname value for user's all-purpose compute or SQL warehouse.
        client_id: the service principal's UUID or Application ID value.
        client_secret: the Secret value for the service principal's OAuth secret.
    """

    integration: model.Integration
    server_hostname: str
    client_id: str
    client_secret: str

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != model.Integration.IntegrationKind.DATABRICKS.value:
            raise DatabricksIntegrationError("Integration provided is not a Databricks integration")
        self.integration = integration

        try:
            self.server_hostname = self.integration.config["server_hostname"]
            self.client_id = self.integration.sensitive_config["client_id"]
            self.client_secret = self.integration.sensitive_config["client_secret"]
        except KeyError as e:
            raise DatabricksIntegrationError(f"Databricks integration is not valid: {str(e)} missing")

    @classmethod
    def integration_from_config(
        cls, team_id: int, server_hostname: str, client_id: str, client_secret: str, created_by: User | None = None
    ) -> model.Integration:
        # first, validate the host
        cls.validate_host(server_hostname)

        config = {
            "server_hostname": server_hostname,
        }
        sensitive_config = {
            "client_id": client_id,
            "client_secret": client_secret,
        }
        integration, _ = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.DATABRICKS.value,
            integration_id=server_hostname,  # Use server_hostname as unique identifier
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @staticmethod
    def validate_host(server_hostname: str):
        """Validate the Databricks host.

        We check the value is a bare hostname (not a full URL) and that it passes our shared SSRF
        guard (rejects unresolvable hosts, internal IPs, cloud-metadata hosts, and internal domain
        patterns). This is a quick check (testing connectivity to a SQL warehouse requires a
        warehouse http_path in addition to these parameters so it not possible to perform a full
        test here).
        """
        # we expect a hostname, not a full URL
        if server_hostname.startswith("http"):
            raise DatabricksIntegrationError(
                f"Databricks integration is not valid: 'server_hostname' should not be a full URL"
            )

        # Databricks is always https, so reuse the shared URL allowlist as the SSRF guard.
        allowed, _reason = is_url_allowed(f"https://{server_hostname}")
        if not allowed:
            raise DatabricksIntegrationError(
                f"Databricks integration error: could not validate hostname '{server_hostname}'"
            )
