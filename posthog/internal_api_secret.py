from django.conf import settings
from django.core.checks import Error, register


def usable_internal_api_secrets() -> list[str]:
    """Internal API secrets accepted when authenticating service-to-service calls: the primary plus
    any still-trusted fallbacks (zero-downtime rotation), dropping empties. Values are
    whitespace-normalized at settings load (posthog/settings/data_stores.py), so this does not
    re-normalize per call.
    """
    return [secret for secret in [settings.INTERNAL_API_SECRET, *settings.INTERNAL_API_SECRET_FALLBACKS] if secret]


@register()
def check_internal_api_secret(app_configs: object, **kwargs: object) -> list[Error]:
    """Fail at startup if a non-dev/test deploy has no INTERNAL_API_SECRET configured, rather than
    rejecting every internal request at runtime. The value itself is not policed — production must
    set a real secret (the default is empty outside DEBUG/TEST), CI may set the dev value.
    """
    if settings.DEBUG or settings.TEST:
        return []
    if usable_internal_api_secrets():
        return []
    return [
        Error(
            "INTERNAL_API_SECRET is not configured.",
            hint="Set INTERNAL_API_SECRET to a non-empty value (it is required outside DEBUG/TEST).",
            id="posthog.E005",
        )
    ]
