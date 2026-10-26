"""Platform credentials whose settings copy is an instance setting, not a Django setting.

Self-hosted deployments edit these in the instance settings UI, and the value there wins over
the environment variable it defaults from. With the service off, the client would read the
environment variable directly and ignore that edit, so the service is only asked when it is on.
With the service on, a key it does not hold falls back to the instance setting, per key, the same
way `settings_fallback` falls back to a Django setting.

Kept apart from `settings_fallback` so that module does not import a Django model.
"""

from posthog.models.instance_setting import get_instance_setting, get_instance_settings

from .callers import CredentialsCaller
from .client import CredentialsServiceClient, credentials_service_enabled
from .settings_fallback import get_many_or_settings, get_or_settings


def _instance_setting(key: str) -> str | None:
    return get_instance_setting(key) or None


def get_or_instance_setting(
    key: str,
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> str:
    """One instance-setting-backed credential, or "" when it is configured nowhere."""
    if not credentials_service_enabled():
        return get_instance_setting(key) or ""
    return get_or_settings(key, caller, client=client, settings_lookup=_instance_setting)


def get_many_or_instance_settings(
    keys: list[str],
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
) -> dict[str, str]:
    """Several instance-setting-backed credentials, "" for each one configured nowhere."""
    if not credentials_service_enabled():
        values = get_instance_settings(keys)
        return {key: values[key] or "" for key in keys}
    return get_many_or_settings(keys, caller, client=client, settings_lookup=_instance_setting)
