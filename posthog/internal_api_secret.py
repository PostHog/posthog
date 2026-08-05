from django.conf import settings


def usable_internal_api_secrets() -> list[str]:
    """Internal API secrets accepted when authenticating service-to-service calls: the primary plus
    any still-trusted fallbacks (zero-downtime rotation), dropping empties. Values are
    whitespace-normalized at settings load (posthog/settings/data_stores.py), so this does not
    re-normalize per call.
    """
    return [secret for secret in [settings.INTERNAL_API_SECRET, *settings.INTERNAL_API_SECRET_FALLBACKS] if secret]
