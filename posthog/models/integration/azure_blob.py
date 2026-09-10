"""Azure Blob Storage integration."""

from posthog.models.user import User
from posthog.security.url_validation import _dev_bypass_enabled, _test_bypass_enabled, is_url_allowed

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

        connection_string = strip_leading_whitespace(connection_string)
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


class EndpointNotAllowedError(ValueError):
    """Distinct error raised when an endpoint is not allowed."""


def validate_azure_blob_connection_string(connection_string: str) -> None:
    """Validate an Azure Blob connection string.

    Extract its parts, evaluate all required settings are included, and check
    that values are supported.
    """
    # Parse exactly as the SDK's parse_connection_str does: no stripping, keys uppercased,
    # later duplicates win. Stricter than the SDK on whitespace-padded keys, which the SDK
    # would silently ignore — a validation/SDK key mismatch is an SSRF bypass.
    settings: dict[str, str] = {}
    for part in connection_string.rstrip(";").split(";"):
        try:
            key, value = part.split("=", maxsplit=1)
        except ValueError:
            raise ValueError("Malformed connection string")
        if key != key.strip():
            raise ValueError("Malformed connection string")
        settings[key.upper()] = value

    if settings.get("USEDEVELOPMENTSTORAGE", "").lower() == "true":
        raise ValueError("Emulator account not supported")

    # HTTPS is required so TLS certificate verification at connect time closes the DNS
    # rebinding window between validation and the SDK's own resolution. Local emulators
    # (Azurite) use HTTP, so the requirement lifts with the dev bypass.
    validation_applies = not (_dev_bypass_enabled() or _test_bypass_enabled())
    protocol = settings.get("DEFAULTENDPOINTSPROTOCOL", "https").lower()
    if protocol not in ("http", "https"):
        raise ValueError("'DefaultEndpointsProtocol' must be 'http' or 'https'")
    if validation_applies and protocol != "https":
        raise ValueError("'DefaultEndpointsProtocol' must be 'https'")

    account_name = settings.get("ACCOUNTNAME")
    if not account_name:
        raise ValueError(
            "Could not extract AccountName from connection string. "
            "Ensure it contains 'AccountName=<your-account-name>;'"
        )

    explicit_endpoints: list[str] = []
    derived_endpoints: list[str] = []

    # For azure blob, we only care about BlobEndpoint.
    # But the docs also mention all these other ones, so we check all of
    # them if present.
    for key in ("BLOBENDPOINT", "FILEENDPOINT", "TABLEENDPOINT", "QUEUEENDPOINT"):
        if key in settings:
            explicit_endpoints.append(settings[key])

    if "BLOBENDPOINT" not in settings:
        suffix = settings.get("ENDPOINTSUFFIX") or "core.windows.net"
        derived_endpoints.append(f"{protocol}://{account_name}.blob.{suffix}")

    for endpoint in explicit_endpoints + derived_endpoints:
        if validation_applies and not endpoint.lower().startswith("https://"):
            raise ValueError("Endpoints in the connection string must use https")

        if validation_applies:
            allowed, error = is_url_allowed(endpoint)
            if not allowed:
                raise EndpointNotAllowedError("Invalid endpoint found in connection string")


def strip_leading_whitespace(conn_str: str) -> str:
    """Remove any leading whitespace from key=value pairs.

    This is rejected by Azure SDK when parsing. In contrast, I like to help our users
    get things right. I do not strip trailing whitespace as I cannot confirm whether
    values can have trailing whitespace, in contrast to keys, which most definitely
    don't.
    """
    return ";".join(value.lstrip() for value in conn_str.split(";"))
