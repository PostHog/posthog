"""Platform credentials, from the credentials service when it is on, else from Django settings.

With the service off, a credential comes straight from its Django setting or env var, so the
service is only asked when it is on. With the service on, a key it does not hold falls back per key,
the same way `settings_fallback` does.
"""

from .callers import CredentialsCaller
from .client import CredentialsServiceClient, credentials_service_enabled
from .settings_fallback import from_django_settings, get_many_or_settings, get_or_settings


def get_or_instance_setting(
    key: str,
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> str:
    """One platform credential, or "" when it is configured nowhere."""
    if not credentials_service_enabled():
        return from_django_settings(key) or ""
    return get_or_settings(key, caller, client=client)


def get_many_or_instance_settings(
    keys: list[str],
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> dict[str, str]:
    """Several platform credentials, "" for each one configured nowhere."""
    if not credentials_service_enabled():
        return {key: from_django_settings(key) or "" for key in keys}
    return get_many_or_settings(keys, caller, client=client)
