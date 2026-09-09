"""Azure Blob Storage integration."""

from posthog.models.user import User
from posthog.security.url_validation import is_url_allowed

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

        try:
            validate_azure_blob_connection_string(connection_string)
        except ValueError as e:
            raise AzureBlobIntegrationError(str(e))

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


def validate_azure_blob_connection_string(connection_string: str) -> None:
    """Validate an Azure Blob connection string.

    Extract its parts, evaluate all required settings are included, and check
    that values are supported.
    """
    # For azure blob, we only care about BlobEndpoint.
    # But the docs also mention all these other ones, so we check all of
    # them if present.
    endpoint_keys = {"blobendpoint", "fileendpoint", "tableendpoint", "queueendpoint"}

    endpoint_suffix: str | None = None
    account_name: str | None = None

    for part in connection_string.split(";"):
        part = part.strip()
        if not part:
            # The SDK accepts a trailing semicolon.
            continue

        try:
            key, value = part.split("=", maxsplit=1)
            key, value = key.lower(), value.lower()
        except Exception:
            raise ValueError("Malformed connection string")

        if key == "usedevelopmentstorage" and value == "true":
            raise ValueError("Emulator account not supported")

        if key in endpoint_keys:
            allowed, error = is_url_allowed(value)
            if not allowed:
                raise ValueError(f"Invalid endpoint found in connection string: {error}")

        if key == "endpointsuffix":
            endpoint_suffix = value

        if key == "accountname":
            account_name = value

    if not account_name:
        raise ValueError(
            "Could not extract AccountName from connection string. "
            "Ensure it contains 'AccountName=<your-account-name>;'"
        )

    if endpoint_suffix:
        derived = f"https://{account_name}.blob.{endpoint_suffix}"
        allowed, error = is_url_allowed(derived)
        if not allowed:
            raise ValueError(f"Invalid 'EndpointSuffix' found in connection string: {error}")
