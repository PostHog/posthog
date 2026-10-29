"""Enums of the integrations SDK."""

from posthog.enums import LabeledStrEnum


class IntegrationAuthType(LabeledStrEnum):
    """How an integration row authenticates with its provider.

    A kind names the provider. One kind can support several auth types, and has one default.
    """

    # A connection that the provider manages: an OAuth grant or an app installation. It has scopes or permissions.
    OAUTH = "oauth", "OAuth"
    # One static secret string: an API key, a personal access token, a bot token or a webhook secret.
    TOKEN = "token", "Token"
    # Several typed-in fields: a host, a user and a password, an access key and a secret, or a service account.
    CREDENTIALS = "credentials", "Credentials"


# The short name for callers. The class keeps the long name, because the OpenAPI enum name comes from it.
AuthType = IntegrationAuthType
