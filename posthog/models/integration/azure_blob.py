"""Azure Blob Storage integration."""

from posthog.models.user import User

from . import model


class AzureBlobIntegrationError(Exception):
    pass


class AzureBlobIntegration:
    """Wraps Integration model to provide encrypted credential storage for Azure Blob Storage.

    Attributes:
        integration: The underlying Integration model instance.
        connection_string: The decrypted Azure Storage connection string.
    """

    integration: model.Integration
    connection_string: str

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != model.Integration.IntegrationKind.AZURE_BLOB.value:
            raise AzureBlobIntegrationError(
                f"Integration provided is not an Azure Blob integration (got kind='{integration.kind}')"
            )
        self.integration = integration

        try:
            self.connection_string = self.integration.sensitive_config["connection_string"]
        except KeyError:
            raise AzureBlobIntegrationError("Azure Blob integration is missing required field: 'connection_string'")

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        connection_string: str,
        created_by: "User | None" = None,
    ) -> model.Integration:
        account_name = cls._extract_account_name(connection_string)
        if not account_name:
            raise AzureBlobIntegrationError(
                "Could not extract AccountName from connection string. "
                "Ensure it contains 'AccountName=<your-account-name>;'"
            )

        config: dict[str, str] = {}
        sensitive_config = {
            "connection_string": connection_string,
        }

        integration, created = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.AZURE_BLOB.value,
            integration_id=account_name,
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
    def _extract_account_name(connection_string: str) -> str | None:
        for part in connection_string.split(";"):
            part = part.strip()
            if part.startswith("AccountName="):
                return part.split("=", 1)[1]
        return None
