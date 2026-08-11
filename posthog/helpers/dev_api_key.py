from typing import TYPE_CHECKING

from django.conf import settings

from posthog.models.utils import hash_key_value

if TYPE_CHECKING:
    from posthog.models.personal_api_key import PersonalAPIKey


def get_local_dev_api_key_value(key: "PersonalAPIKey") -> str | None:
    """Return the plaintext of the seeded local-dev key, or None for any other key.

    Personal API keys never persist plaintext, so the only key whose value can be recovered is the
    deterministic dev key seeded by `manage.py setup_local_api_key`, whose value is the
    settings.DEV_API_KEY constant. Identifying it means hashing that constant and comparing against
    the stored hash, which reveals nothing that is not already in the repository.
    """
    # The gate is read on every call rather than resolved once at import, so that @override_settings
    # in tests and a changed env between processes both take effect.
    if not settings.DEBUG or not settings.ALLOW_DEV_API_KEY_REVEAL or settings.CLOUD_DEPLOYMENT:
        return None
    # DEV_API_KEY is defined in ee/settings.py, which OSS builds never load, so this must tolerate
    # the attribute being absent entirely.
    dev_api_key = getattr(settings, "DEV_API_KEY", None)
    if not dev_api_key or not key.secure_value:
        return None
    if key.secure_value != hash_key_value(dev_api_key):
        return None
    return dev_api_key
