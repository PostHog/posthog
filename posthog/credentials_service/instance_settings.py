"""Platform credentials whose settings copy may still be an instance setting.

Self-hosted deployments edit instance settings in the UI, and the value there wins over the
environment variable it defaults from. With the service off, the client would read the environment
variable directly and ignore that edit, so the service is only asked when it is on. With the service
on, a key it does not hold falls back per key, the same way `settings_fallback` does.

A key still in `CONSTANCE_CONFIG` falls back to its instance setting. Any other key falls back to the
Django setting of the same name, so a key moves from instance settings to Django settings by
deleting it from `CONSTANCE_CONFIG`, with no change to its callers.

Kept apart from `settings_fallback` so that module does not import a Django model.
"""

from posthog.models.instance_setting import get_instance_setting, get_instance_settings
from posthog.settings import CONSTANCE_CONFIG

from .callers import CredentialsCaller
from .client import CredentialsServiceClient, credentials_service_enabled
from .settings_fallback import from_django_settings, get_many_or_settings, get_or_settings


def _setting(key: str) -> str | None:
    if key in CONSTANCE_CONFIG:
        return get_instance_setting(key) or None
    return from_django_settings(key)


def get_or_instance_setting(
    key: str,
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> str:
    """One platform credential, or "" when it is configured nowhere."""
    if not credentials_service_enabled():
        return _setting(key) or ""
    return get_or_settings(key, caller, client=client, settings_lookup=_setting)


def get_many_or_instance_settings(
    keys: list[str],
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> dict[str, str]:
    """Several platform credentials, "" for each one configured nowhere."""
    if not credentials_service_enabled():
        instance_keys = [key for key in keys if key in CONSTANCE_CONFIG]
        values = get_instance_settings(instance_keys) if instance_keys else {}
        return {key: (values[key] if key in CONSTANCE_CONFIG else from_django_settings(key)) or "" for key in keys}
    return get_many_or_settings(keys, caller, client=client, settings_lookup=_setting)
